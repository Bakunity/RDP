package main

import (
    "context"
    "crypto/hmac"
    "crypto/rand"
    "crypto/sha256"
    "encoding/base64"
    "encoding/json"
    "errors"
    "flag"
    "fmt"
    "io"
    "log"
    "net"
    "net/http"
    "os"
    "os/signal"
    "path/filepath"
    "sort"
    "strings"
    "sync"
    "syscall"
    "time"

    libp2p "github.com/libp2p/go-libp2p"
    corecrypto "github.com/libp2p/go-libp2p/core/crypto"
    "github.com/libp2p/go-libp2p/core/host"
    "github.com/libp2p/go-libp2p/core/network"
    "github.com/libp2p/go-libp2p/core/peer"
    "github.com/libp2p/go-libp2p/core/protocol"
    "github.com/libp2p/go-libp2p/p2p/host/autorelay"
    "github.com/libp2p/go-libp2p/p2p/protocol/holepunch"
    circuitclient "github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/client"
    circuitrelay "github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/relay"
    ma "github.com/multiformats/go-multiaddr"
)

const (
    transportVersion = "0.1.0"
    rdpProtocol      = protocol.ID("/bakunity/rdp/1.0.0")
    authMagic        = "BKT1"
    forwardReprobeInterval = 15 * time.Second
)

var transportBuildRef = "dev"

type nodeConfig struct {
    Role         string `json:"role"`
    IdentityPath string `json:"identity_path"`
    RelayAddr    string `json:"relay_addr"`
    ControlAddr  string `json:"control_addr"`
    Target       string `json:"target"`
    SharedSecret string `json:"shared_secret"`
}

type forwardSpec struct {
    Key          string `json:"key"`
    PeerID       string `json:"peer_id"`
    SharedSecret string `json:"shared_secret"`
    Listen       string `json:"listen"`
    Mode         string `json:"mode"`
}

type forwardRuntime struct {
    spec              forwardSpec
    listener          net.Listener
    stop              chan struct{}
    stopOnce          sync.Once
    stateMu           sync.RWMutex
    activeSessions    int
    lastStreamPath    string
    lastStreamAt      time.Time
    lastDirectError   string
    lastDirectAttempt time.Time
}

type nodeRuntime struct {
    host       host.Host
    relayInfo  *peer.AddrInfo
    cfg        nodeConfig
    holePunch  *holePunchTracer
    mu                 sync.RWMutex
    forwards           map[string]*forwardRuntime
    reservationReady   bool
    reservationUpdated time.Time
    inboundMu           sync.RWMutex
    inboundActive       int
    inboundLastPath     string
    inboundLastAt       time.Time
}

type holePunchEventState struct {
    Timestamp   int64    `json:"timestamp"`
    Type        string   `json:"type"`
    Success     *bool    `json:"success,omitempty"`
    Error       string   `json:"error,omitempty"`
    Attempt     int      `json:"attempt,omitempty"`
    RemoteAddrs []string `json:"remote_addrs,omitempty"`
    RTTMillis   int64    `json:"rtt_ms,omitempty"`
}

type holePunchTracer struct {
    mu     sync.RWMutex
    latest map[peer.ID]holePunchEventState
}

func newHolePunchTracer() *holePunchTracer {
    return &holePunchTracer{
        latest: make(map[peer.ID]holePunchEventState),
    }
}

func boolPtr(value bool) *bool {
    return &value
}

func (t *holePunchTracer) Trace(evt *holepunch.Event) {
    if evt == nil || evt.Remote == "" {
        return
    }
    state := holePunchEventState{
        Timestamp: evt.Timestamp,
        Type:      evt.Type,
    }
    switch detail := evt.Evt.(type) {
    case *holepunch.DirectDialEvt:
        state.Success = boolPtr(detail.Success)
        state.Error = detail.Error
    case *holepunch.StartHolePunchEvt:
        state.RemoteAddrs = append(
            []string(nil),
            detail.RemoteAddrs...,
        )
        state.RTTMillis = detail.RTT.Milliseconds()
    case *holepunch.EndHolePunchEvt:
        state.Success = boolPtr(detail.Success)
        state.Error = detail.Error
    case *holepunch.HolePunchAttemptEvt:
        state.Attempt = detail.Attempt
    case *holepunch.ProtocolErrorEvt:
        state.Error = detail.Error
    }
    if len(state.Error) > 500 {
        state.Error = state.Error[:500]
    }
    if len(state.RemoteAddrs) > 16 {
        state.RemoteAddrs = state.RemoteAddrs[:16]
    }
    t.mu.Lock()
    t.latest[evt.Remote] = state
    t.mu.Unlock()
}

func (t *holePunchTracer) get(pid peer.ID) holePunchEventState {
    t.mu.RLock()
    defer t.mu.RUnlock()
    return t.latest[pid]
}

type relayACL struct {
    mu      sync.RWMutex
    allowed map[peer.ID]struct{}
}

func newRelayACL() *relayACL {
    return &relayACL{allowed: make(map[peer.ID]struct{})}
}

func (a *relayACL) allow(id peer.ID) {
    a.mu.Lock()
    defer a.mu.Unlock()
    a.allowed[id] = struct{}{}
}

func (a *relayACL) AllowReserve(id peer.ID, _ ma.Multiaddr) bool {
    a.mu.RLock()
    defer a.mu.RUnlock()
    _, ok := a.allowed[id]
    return ok
}

func (a *relayACL) AllowConnect(
    src peer.ID,
    _ ma.Multiaddr,
    dest peer.ID,
) bool {
    a.mu.RLock()
    defer a.mu.RUnlock()
    _, sourceOK := a.allowed[src]
    _, destOK := a.allowed[dest]
    return sourceOK && destOK
}

func (a *relayACL) count() int {
    a.mu.RLock()
    defer a.mu.RUnlock()
    return len(a.allowed)
}

func main() {
    log.SetFlags(log.LstdFlags | log.LUTC | log.Lmicroseconds)
    if len(os.Args) < 2 {
        fatalf("usage: bakunity-transport relay|node|id")
    }

    switch os.Args[1] {
    case "relay":
        runRelay(os.Args[2:])
    case "node":
        runNode(os.Args[2:])
    case "id":
        printIdentity(os.Args[2:])
    default:
        fatalf("unknown command: %s", os.Args[1])
    }
}

func fatalf(format string, args ...any) {
    log.Printf(format, args...)
    os.Exit(1)
}

func contextWithSignals() (context.Context, context.CancelFunc) {
    ctx, cancel := signal.NotifyContext(
        context.Background(),
        os.Interrupt,
        syscall.SIGTERM,
    )
    return ctx, cancel
}

func loadOrCreateIdentity(path string) (corecrypto.PrivKey, error) {
    if strings.TrimSpace(path) == "" {
        return nil, errors.New("identity path is required")
    }
    if raw, err := os.ReadFile(path); err == nil {
        key, err := corecrypto.UnmarshalPrivateKey(raw)
        if err != nil {
            return nil, fmt.Errorf("parse identity: %w", err)
        }
        return key, nil
    } else if !os.IsNotExist(err) {
        return nil, fmt.Errorf("read identity: %w", err)
    }

    key, _, err := corecrypto.GenerateEd25519Key(rand.Reader)
    if err != nil {
        return nil, fmt.Errorf("generate identity: %w", err)
    }
    raw, err := corecrypto.MarshalPrivateKey(key)
    if err != nil {
        return nil, fmt.Errorf("marshal identity: %w", err)
    }
    if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
        return nil, fmt.Errorf("create identity dir: %w", err)
    }
    temp := path + ".tmp"
    if err := os.WriteFile(temp, raw, 0o600); err != nil {
        return nil, fmt.Errorf("write identity: %w", err)
    }
    if err := os.Chmod(temp, 0o600); err != nil && !errors.Is(err, os.ErrPermission) {
        return nil, fmt.Errorf("chmod identity: %w", err)
    }
    if err := os.Rename(temp, path); err != nil {
        return nil, fmt.Errorf("install identity: %w", err)
    }
    return key, nil
}

func printIdentity(args []string) {
    fs := flag.NewFlagSet("id", flag.ExitOnError)
    identity := fs.String("identity", "", "identity key path")
    _ = fs.Parse(args)

    key, err := loadOrCreateIdentity(*identity)
    if err != nil {
        fatalf("identity: %v", err)
    }
    id, err := peer.IDFromPrivateKey(key)
    if err != nil {
        fatalf("peer id: %v", err)
    }
    fmt.Println(id.String())
}

func runRelay(args []string) {
    fs := flag.NewFlagSet("relay", flag.ExitOnError)
    identity := fs.String("identity", "", "identity key path")
    port := fs.Int("port", 7444, "public TCP/UDP port")
    control := fs.String("control", "127.0.0.1:7445", "local control address")
    _ = fs.Parse(args)

    key, err := loadOrCreateIdentity(*identity)
    if err != nil {
        fatalf("identity: %v", err)
    }
    h, err := libp2p.New(
        libp2p.Identity(key),
        libp2p.ListenAddrStrings(
            fmt.Sprintf("/ip4/0.0.0.0/tcp/%d", *port),
            fmt.Sprintf("/ip4/0.0.0.0/udp/%d/quic-v1", *port),
        ),
        libp2p.EnableNATService(),
    )
    if err != nil {
        fatalf("create relay host: %v", err)
    }
    defer h.Close()

    acl := newRelayACL()
    resources := circuitrelay.DefaultResources()
    resources.Limit = &circuitrelay.RelayLimit{
        Duration: 12 * time.Hour,
        Data:     16 << 30,
    }
    resources.MaxReservations = 256
    resources.MaxCircuits = 8
    resources.BufferSize = 64 * 1024
    relayService, err := circuitrelay.New(
        h,
        circuitrelay.WithACL(acl),
        circuitrelay.WithResources(resources),
    )
    if err != nil {
        fatalf("start relay service: %v", err)
    }
    defer relayService.Close()

    mux := http.NewServeMux()
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, http.StatusOK, map[string]any{
            "status": "pass",
            "version": transportVersion,
            "build_ref": transportBuildRef,
        })
    })
    mux.HandleFunc("/allow", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodPost {
            writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false})
            return
        }
        defer r.Body.Close()
        var body struct {
            PeerID string `json:"peer_id"`
        }
        dec := json.NewDecoder(io.LimitReader(r.Body, 8*1024))
        dec.DisallowUnknownFields()
        if err := dec.Decode(&body); err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
            return
        }
        id, err := peer.Decode(strings.TrimSpace(body.PeerID))
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": "invalid peer_id"})
            return
        }
        acl.allow(id)
        writeJSON(w, http.StatusOK, map[string]any{"ok": true})
    })
    mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
        addrs := make([]string, 0, len(h.Addrs()))
        for _, addr := range h.Addrs() {
            addrs = append(addrs, addr.String())
        }
        sort.Strings(addrs)

        peers := make([]map[string]any, 0)
        for _, conn := range h.Network().Conns() {
            if conn.RemotePeer() == h.ID() {
                continue
            }
            peers = append(peers, map[string]any{
                "peer_id": conn.RemotePeer().String(),
                "remote_addr": conn.RemoteMultiaddr().String(),
                "direction": conn.Stat().Direction.String(),
                "limited": conn.Stat().Limited,
            })
        }
        sort.Slice(peers, func(i, j int) bool {
            left := fmt.Sprint(peers[i]["peer_id"], "|", peers[i]["remote_addr"])
            right := fmt.Sprint(peers[j]["peer_id"], "|", peers[j]["remote_addr"])
            return left < right
        })

        writeJSON(w, http.StatusOK, map[string]any{
            "ok": true,
            "version": transportVersion,
            "build_ref": transportBuildRef,
            "peer_id": h.ID().String(),
            "addrs": addrs,
            "allowed_peers": acl.count(),
            "connected_peers": peers,
        })
    })

    server := &http.Server{
        Addr:              *control,
        Handler:           mux,
        ReadHeaderTimeout: 5 * time.Second,
    }
    go func() {
        if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
            log.Printf("control server: %v", err)
        }
    }()

    ctx, cancel := contextWithSignals()
    defer cancel()
    log.Printf("BAKUNITY_TRANSPORT_RELAY=READY peer_id=%s", h.ID())
    <-ctx.Done()

    shutdownCtx, stop := context.WithTimeout(context.Background(), 5*time.Second)
    defer stop()
    _ = server.Shutdown(shutdownCtx)
}

func readNodeConfig(path string) (nodeConfig, error) {
    raw, err := os.ReadFile(path)
    if err != nil {
        return nodeConfig{}, err
    }
    var cfg nodeConfig
    if err := json.Unmarshal(raw, &cfg); err != nil {
        return nodeConfig{}, err
    }
    cfg.Role = strings.ToLower(strings.TrimSpace(cfg.Role))
    if cfg.Role != "host" && cfg.Role != "connector" && cfg.Role != "both" {
        return nodeConfig{}, errors.New("role must be host, connector, or both")
    }
    if cfg.ControlAddr == "" {
        cfg.ControlAddr = "127.0.0.1:48389"
    }
    if cfg.Target == "" {
        cfg.Target = "127.0.0.1:3389"
    }
    if cfg.IdentityPath == "" {
        return nodeConfig{}, errors.New("identity_path is required")
    }
    if cfg.RelayAddr == "" {
        return nodeConfig{}, errors.New("relay_addr is required")
    }
    if (cfg.Role == "host" || cfg.Role == "both") && cfg.SharedSecret == "" {
        return nodeConfig{}, errors.New("shared_secret is required for host role")
    }
    return cfg, nil
}

func runNode(args []string) {
    fs := flag.NewFlagSet("node", flag.ExitOnError)
    configPath := fs.String("config", "", "node config JSON path")
    _ = fs.Parse(args)

    cfg, err := readNodeConfig(*configPath)
    if err != nil {
        fatalf("config: %v", err)
    }
    key, err := loadOrCreateIdentity(cfg.IdentityPath)
    if err != nil {
        fatalf("identity: %v", err)
    }

    relayAddr, err := ma.NewMultiaddr(cfg.RelayAddr)
    if err != nil {
        fatalf("relay multiaddr: %v", err)
    }
    relayInfo, err := peer.AddrInfoFromP2pAddr(relayAddr)
    if err != nil {
        fatalf("relay peer: %v", err)
    }

    hpTracer := newHolePunchTracer()
    h, err := libp2p.New(
        libp2p.Identity(key),
        libp2p.ListenAddrStrings(
            "/ip4/0.0.0.0/tcp/0",
            "/ip4/0.0.0.0/udp/0/quic-v1",
        ),
        libp2p.EnableRelay(),
        libp2p.EnableAutoRelayWithStaticRelays(
            []peer.AddrInfo{*relayInfo},
            autorelay.WithBootDelay(0),
            autorelay.WithMinCandidates(1),
            autorelay.WithNumRelays(1),
        ),
        libp2p.EnableHolePunching(
            holepunch.WithTracer(hpTracer),
            holepunch.DirectDialTimeout(5*time.Second),
        ),
        libp2p.NATPortMap(),
        libp2p.ForceReachabilityPrivate(),
    )
    if err != nil {
        fatalf("create node: %v", err)
    }
    defer h.Close()

    runtime := &nodeRuntime{
        host:      h,
        relayInfo: relayInfo,
        cfg:       cfg,
        holePunch: hpTracer,
        forwards:  map[string]*forwardRuntime{},
    }

    if cfg.Role == "host" || cfg.Role == "both" {
        h.SetStreamHandler(rdpProtocol, runtime.handleRDPStream)
    }

    ctx, cancel := contextWithSignals()
    defer cancel()

    server := runtime.controlServer()
    go func() {
        if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
            log.Printf("control server: %v", err)
            cancel()
        }
    }()
    if err := runtime.ensureRelay(ctx, true); err != nil {
        log.Printf("initial relay admission pending: %v", err)
    }
    go runtime.maintainRelay(ctx)

    log.Printf(
        "BAKUNITY_TRANSPORT_NODE=READY role=%s peer_id=%s",
        cfg.Role,
        h.ID(),
    )
    <-ctx.Done()

    runtime.closeForwards()
    shutdownCtx, stop := context.WithTimeout(context.Background(), 5*time.Second)
    defer stop()
    _ = server.Shutdown(shutdownCtx)
}

func (n *nodeRuntime) ensureRelay(ctx context.Context, reserve bool) error {
    connectCtx, cancel := context.WithTimeout(ctx, 12*time.Second)
    defer cancel()
    if err := n.host.Connect(connectCtx, *n.relayInfo); err != nil {
        return err
    }
    if reserve && (n.cfg.Role == "host" || n.cfg.Role == "both") {
        if _, err := circuitclient.Reserve(connectCtx, n.host, *n.relayInfo); err != nil {
            return fmt.Errorf("reserve relay: %w", err)
        }
        n.mu.Lock()
        n.reservationReady = true
        n.reservationUpdated = time.Now()
        n.mu.Unlock()
    }
    return nil
}

func (n *nodeRuntime) reservationNeedsRefresh() bool {
    if n.cfg.Role != "host" && n.cfg.Role != "both" {
        return false
    }
    n.mu.RLock()
    ready := n.reservationReady
    updated := n.reservationUpdated
    n.mu.RUnlock()
    return !ready || time.Since(updated) >= 30*time.Minute
}

func (n *nodeRuntime) maintainRelay(ctx context.Context) {
    ticker := time.NewTicker(5 * time.Second)
    defer ticker.Stop()
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            connected := n.host.Network().Connectedness(n.relayInfo.ID) == network.Connected
            reserve := n.reservationNeedsRefresh()
            if !connected || reserve {
                if err := n.ensureRelay(ctx, reserve); err != nil {
                    log.Printf("relay maintenance: %v", err)
                }
            }
        }
    }
}

func (n *nodeRuntime) handleRDPStream(stream network.Stream) {
    defer stream.Close()
    if err := verifyStreamAuth(stream, n.cfg.SharedSecret); err != nil {
        log.Printf("reject stream from %s: %v", stream.Conn().RemotePeer(), err)
        _ = stream.Reset()
        return
    }

    target, err := net.DialTimeout("tcp", n.cfg.Target, 5*time.Second)
    if err != nil {
        log.Printf("local RDP target %s: %v", n.cfg.Target, err)
        _ = stream.Reset()
        return
    }
    defer target.Close()

    streamPath := "direct"
    if stream.Conn().Stat().Limited {
        streamPath = "relay"
    }
    n.inboundMu.Lock()
    n.inboundActive++
    n.inboundLastPath = streamPath
    n.inboundLastAt = time.Now()
    n.inboundMu.Unlock()
    defer func() {
        n.inboundMu.Lock()
        if n.inboundActive > 0 {
            n.inboundActive--
        }
        n.inboundMu.Unlock()
    }()

    bridge(stream, target)
}

func bridge(a io.ReadWriteCloser, b io.ReadWriteCloser) {
    done := make(chan struct{}, 2)
    go func() {
        _, _ = io.Copy(a, b)
        done <- struct{}{}
    }()
    go func() {
        _, _ = io.Copy(b, a)
        done <- struct{}{}
    }()
    <-done
}

func decodeSecret(value string) ([]byte, error) {
    secret, err := base64.RawURLEncoding.DecodeString(strings.TrimSpace(value))
    if err != nil {
        return nil, err
    }
    if len(secret) < 24 {
        return nil, errors.New("shared secret is too short")
    }
    return secret, nil
}

func authMAC(secret []byte, nonce []byte, peerID string) []byte {
    mac := hmac.New(sha256.New, secret)
    _, _ = mac.Write(nonce)
    _, _ = mac.Write([]byte(peerID))
    return mac.Sum(nil)
}

func writeStreamAuth(stream network.Stream, secretValue string, localPeer peer.ID) error {
    secret, err := decodeSecret(secretValue)
    if err != nil {
        return err
    }
    nonce := make([]byte, 16)
    if _, err := rand.Read(nonce); err != nil {
        return err
    }
    payload := make([]byte, 0, 4+16+32)
    payload = append(payload, []byte(authMagic)...)
    payload = append(payload, nonce...)
    payload = append(payload, authMAC(secret, nonce, localPeer.String())...)
    _ = stream.SetWriteDeadline(time.Now().Add(5 * time.Second))
    _, err = stream.Write(payload)
    _ = stream.SetWriteDeadline(time.Time{})
    return err
}

func verifyStreamAuth(stream network.Stream, secretValue string) error {
    secret, err := decodeSecret(secretValue)
    if err != nil {
        return err
    }
    payload := make([]byte, 4+16+32)
    _ = stream.SetReadDeadline(time.Now().Add(5 * time.Second))
    if _, err := io.ReadFull(stream, payload); err != nil {
        return err
    }
    _ = stream.SetReadDeadline(time.Time{})
    if string(payload[:4]) != authMagic {
        return errors.New("invalid auth magic")
    }
    nonce := payload[4:20]
    expected := authMAC(secret, nonce, stream.Conn().RemotePeer().String())
    if !hmac.Equal(expected, payload[20:]) {
        return errors.New("invalid transport authorization")
    }
    return nil
}

func (n *nodeRuntime) controlServer() *http.Server {
    mux := http.NewServeMux()
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, http.StatusOK, map[string]any{
            "status": "pass",
            "version": transportVersion,
            "build_ref": transportBuildRef,
        })
    })
    mux.HandleFunc("/status", n.handleStatus)
    mux.HandleFunc("/forward", n.handleForward)

    return &http.Server{
        Addr:              n.cfg.ControlAddr,
        Handler:           mux,
        ReadHeaderTimeout: 5 * time.Second,
    }
}

func (n *nodeRuntime) handleStatus(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false})
        return
    }
    n.mu.RLock()
    forwards := make([]map[string]any, 0, len(n.forwards))
    for _, runtime := range n.forwards {
        pid, _ := peer.Decode(runtime.spec.PeerID)
        directConns, relayConns := n.connectionCounts(pid)
        peerAddrs := make([]string, 0)
        if pid != "" {
            for _, addr := range n.host.Peerstore().Addrs(pid) {
                peerAddrs = append(peerAddrs, addr.String())
            }
            sort.Strings(peerAddrs)
        }
        directAttemptAt := int64(0)
        if !runtime.lastDirectAttempt.IsZero() {
            directAttemptAt = runtime.lastDirectAttempt.Unix()
        }
        path := n.pathForPeer(pid)
        directDialError := runtime.lastDirectError
        if path == "direct" {
            directDialError = ""
        }
        runtime.stateMu.RLock()
        activeSessions := runtime.activeSessions
        lastStreamPath := runtime.lastStreamPath
        lastStreamAt := int64(0)
        if !runtime.lastStreamAt.IsZero() {
            lastStreamAt = runtime.lastStreamAt.Unix()
        }
        runtime.stateMu.RUnlock()
        hpEvent := n.holePunch.get(pid)
        forwards = append(forwards, map[string]any{
            "key": runtime.spec.Key,
            "peer_id": runtime.spec.PeerID,
            "listen": runtime.spec.Listen,
            "mode": runtime.spec.Mode,
            "path": path,
            "direct_connections": directConns,
            "relay_connections": relayConns,
            "peer_addrs": peerAddrs,
            "direct_dial_error": directDialError,
            "direct_dial_attempt_at": directAttemptAt,
            "active_sessions": activeSessions,
            "last_stream_path": lastStreamPath,
            "last_stream_at": lastStreamAt,
            "hole_punch": hpEvent,
        })
    }
    n.mu.RUnlock()
    sort.Slice(forwards, func(i, j int) bool {
        return fmt.Sprint(forwards[i]["key"]) < fmt.Sprint(forwards[j]["key"])
    })

    localAddrs := make([]string, 0, len(n.host.Addrs()))
    for _, addr := range n.host.Addrs() {
        localAddrs = append(localAddrs, addr.String())
    }
    sort.Strings(localAddrs)

    n.inboundMu.RLock()
    inboundActive := n.inboundActive
    inboundLastPath := n.inboundLastPath
    inboundLastAt := int64(0)
    if !n.inboundLastAt.IsZero() {
        inboundLastAt = n.inboundLastAt.Unix()
    }
    n.inboundMu.RUnlock()

    writeJSON(w, http.StatusOK, map[string]any{
        "ok": true,
        "version": transportVersion,
            "build_ref": transportBuildRef,
        "role": n.cfg.Role,
        "peer_id": n.host.ID().String(),
        "relay_peer_id": n.relayInfo.ID.String(),
        "relay_connected": n.host.Network().Connectedness(n.relayInfo.ID) == network.Connected,
        "inbound_active_sessions": inboundActive,
        "inbound_last_stream_path": inboundLastPath,
        "inbound_last_stream_at": inboundLastAt,
        "addrs": localAddrs,
        "forwards": forwards,
    })
}

func (n *nodeRuntime) handleForward(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false})
        return
    }
    defer r.Body.Close()
    dec := json.NewDecoder(io.LimitReader(r.Body, 64*1024))
    dec.DisallowUnknownFields()
    var spec forwardSpec
    if err := dec.Decode(&spec); err != nil {
        writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
        return
    }
    if err := n.ensureForward(spec); err != nil {
        writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
        return
    }
    path, err := n.probeForward(spec)
    if err != nil {
        writeJSON(
            w,
            http.StatusServiceUnavailable,
            map[string]any{"ok": false, "error": err.Error(), "path": path},
        )
        return
    }
    writeJSON(w, http.StatusOK, map[string]any{
        "ok": true,
        "path": path,
        "listen": spec.Listen,
    })
}

func (n *nodeRuntime) ensureForward(spec forwardSpec) error {
    spec.Key = strings.TrimSpace(spec.Key)
    spec.PeerID = strings.TrimSpace(spec.PeerID)
    spec.Listen = strings.TrimSpace(spec.Listen)
    if spec.Key == "" || spec.PeerID == "" || spec.Listen == "" {
        return errors.New("key, peer_id, shared_secret and listen are required")
    }
    spec.Mode = strings.ToLower(strings.TrimSpace(spec.Mode))
    if spec.Mode == "" {
        spec.Mode = "auto"
    }
    if spec.Mode != "auto" && spec.Mode != "direct" {
        return errors.New("mode must be auto or direct")
    }
    if _, err := decodeSecret(spec.SharedSecret); err != nil {
        return fmt.Errorf("shared_secret: %w", err)
    }
    if _, err := peer.Decode(spec.PeerID); err != nil {
        return fmt.Errorf("peer_id: %w", err)
    }
    hostPart, _, err := net.SplitHostPort(spec.Listen)
    if err != nil {
        return fmt.Errorf("listen: %w", err)
    }
    ip := net.ParseIP(hostPart)
    if ip == nil || !ip.IsLoopback() {
        return errors.New("forward listener must be loopback-only")
    }

    n.mu.Lock()
    defer n.mu.Unlock()
    if existing := n.forwards[spec.Key]; existing != nil {
        if existing.spec.PeerID == spec.PeerID &&
            existing.spec.Listen == spec.Listen &&
            existing.spec.Mode == spec.Mode &&
            hmac.Equal([]byte(existing.spec.SharedSecret), []byte(spec.SharedSecret)) {
            return nil
        }
        existing.stopOnce.Do(func() { close(existing.stop) })
        _ = existing.listener.Close()
        delete(n.forwards, spec.Key)
    }

    listener, err := net.Listen("tcp", spec.Listen)
    if err != nil {
        return err
    }
    runtime := &forwardRuntime{
        spec:     spec,
        listener: listener,
        stop:     make(chan struct{}),
    }
    n.forwards[spec.Key] = runtime
    go n.serveForward(runtime)
    go n.maintainForwardPath(runtime)
    return nil
}

func (n *nodeRuntime) probeForward(spec forwardSpec) (string, error) {
    pid, err := peer.Decode(spec.PeerID)
    if err != nil {
        return "unavailable", err
    }
    ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
    defer cancel()

    if err := n.connectPeer(ctx, pid); err != nil {
        return "unavailable", fmt.Errorf("native path unavailable: %w", err)
    }

    if n.pathForPeer(pid) != "direct" {
        directTimeout := 2500 * time.Millisecond
        if spec.Mode == "direct" {
            directTimeout = 5 * time.Second
        }
        directCtx, stopDirect := context.WithTimeout(
            context.Background(),
            directTimeout,
        )
        directErr := n.tryDirectPeer(directCtx, pid)
        stopDirect()
        n.recordDirectAttempt(spec.Key, directErr)
        if directErr != nil {
            log.Printf(
                "direct dial peer %s key=%s: %v",
                pid,
                spec.Key,
                directErr,
            )
        }
    }

    grace := 2500 * time.Millisecond
    if spec.Mode == "direct" {
        grace = 8 * time.Second
    }
    deadline := time.Now().Add(grace)
    for time.Now().Before(deadline) {
        if n.pathForPeer(pid) == "direct" {
            n.clearDirectError(spec.Key)
            return "direct", nil
        }
        time.Sleep(100 * time.Millisecond)
    }
    if spec.Mode == "direct" {
        return n.pathForPeer(pid), errors.New("direct Bakunity path unavailable after hole-punch grace period")
    }
    return n.pathForPeer(pid), nil
}

func (n *nodeRuntime) maintainForwardPath(runtime *forwardRuntime) {
    pid, err := peer.Decode(runtime.spec.PeerID)
    if err != nil {
        return
    }

    ticker := time.NewTicker(forwardReprobeInterval)
    defer ticker.Stop()

    for {
        select {
        case <-runtime.stop:
            return
        case <-ticker.C:
            if n.pathForPeer(pid) == "direct" {
                n.clearDirectError(runtime.spec.Key)
                continue
            }

            ctx, cancel := context.WithTimeout(
                context.Background(),
                8*time.Second,
            )
            attemptErr := n.connectPeer(ctx, pid)
            if attemptErr == nil && n.pathForPeer(pid) != "direct" {
                directCtx, stopDirect := context.WithTimeout(
                    context.Background(),
                    4*time.Second,
                )
                attemptErr = n.tryDirectPeer(directCtx, pid)
                stopDirect()
            }
            cancel()
            n.recordDirectAttempt(runtime.spec.Key, attemptErr)
        }
    }
}

func (n *nodeRuntime) serveForward(runtime *forwardRuntime) {
    for {
        conn, err := runtime.listener.Accept()
        if err != nil {
            return
        }
        go n.handleForwardConn(runtime, conn)
    }
}

func (n *nodeRuntime) handleForwardConn(runtime *forwardRuntime, local net.Conn) {
    defer local.Close()
    spec := runtime.spec
    pid, err := peer.Decode(spec.PeerID)
    if err != nil {
        return
    }

    ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
    defer cancel()
    if err := n.connectPeer(ctx, pid); err != nil {
        log.Printf("connect peer %s: %v", pid, err)
        return
    }

    if n.pathForPeer(pid) != "direct" {
        directCtx, stopDirect := context.WithTimeout(
            context.Background(),
            2500*time.Millisecond,
        )
        directErr := n.tryDirectPeer(directCtx, pid)
        stopDirect()
        n.recordDirectAttempt(spec.Key, directErr)
        if directErr != nil {
            log.Printf(
                "direct dial peer %s key=%s: %v",
                pid,
                spec.Key,
                directErr,
            )
        }
    }

    punchDeadline := time.Now().Add(2500 * time.Millisecond)
    for time.Now().Before(punchDeadline) {
        if n.pathForPeer(pid) == "direct" {
            break
        }
        time.Sleep(100 * time.Millisecond)
    }
    if spec.Mode == "direct" && n.pathForPeer(pid) != "direct" {
        log.Printf("direct path unavailable for %s", pid)
        return
    }

    streamCtx := network.WithAllowLimitedConn(ctx, "bakunity-rdp")
    stream, err := n.host.NewStream(streamCtx, pid, rdpProtocol)
    if err != nil {
        log.Printf("open RDP stream %s: %v", pid, err)
        return
    }

    streamPath := "direct"
    if stream.Conn().Stat().Limited {
        streamPath = "relay"
    }
    runtime.stateMu.Lock()
    runtime.activeSessions++
    runtime.lastStreamPath = streamPath
    runtime.lastStreamAt = time.Now()
    runtime.stateMu.Unlock()
    defer func() {
        runtime.stateMu.Lock()
        if runtime.activeSessions > 0 {
            runtime.activeSessions--
        }
        runtime.stateMu.Unlock()
    }()

    if err := writeStreamAuth(stream, spec.SharedSecret, n.host.ID()); err != nil {
        _ = stream.Reset()
        return
    }
    bridge(local, stream)
}

func (n *nodeRuntime) clearDirectError(key string) {
    n.mu.Lock()
    defer n.mu.Unlock()
    if runtime := n.forwards[key]; runtime != nil {
        runtime.lastDirectError = ""
    }
}

func (n *nodeRuntime) recordDirectAttempt(key string, err error) {
    message := ""
    if err != nil {
        message = err.Error()
        if len(message) > 500 {
            message = message[:500]
        }
    }
    n.mu.Lock()
    defer n.mu.Unlock()
    if runtime := n.forwards[key]; runtime != nil {
        runtime.lastDirectAttempt = time.Now()
        runtime.lastDirectError = message
    }
}

func (n *nodeRuntime) tryDirectPeer(
    ctx context.Context,
    pid peer.ID,
) error {
    if n.pathForPeer(pid) == "direct" {
        return nil
    }

    known := n.host.Peerstore().Addrs(pid)
    directAddrs := make([]ma.Multiaddr, 0, len(known))
    for _, addr := range known {
        if strings.Contains(addr.String(), "/p2p-circuit") {
            continue
        }
        directAddrs = append(directAddrs, addr)
    }
    if len(directAddrs) == 0 {
        return errors.New("no direct peer addresses known")
    }

    directCtx := network.WithForceDirectDial(
        ctx,
        "bakunity-direct-upgrade",
    )
    directCtx = network.WithDialPeerTimeout(
        directCtx,
        2500*time.Millisecond,
    )
    err := n.host.Connect(
        directCtx,
        peer.AddrInfo{
            ID:    pid,
            Addrs: directAddrs,
        },
    )
    if err != nil {
        return fmt.Errorf("force direct dial: %w", err)
    }
    if n.pathForPeer(pid) != "direct" {
        return errors.New("force direct dial completed without direct connection")
    }
    return nil
}

func (n *nodeRuntime) connectPeer(ctx context.Context, pid peer.ID) error {
    if n.host.Network().Connectedness(pid) == network.Connected {
        return nil
    }
    relayCircuit, err := ma.NewMultiaddr(
        fmt.Sprintf(
            "/p2p/%s/p2p-circuit/p2p/%s",
            n.relayInfo.ID,
            pid,
        ),
    )
    if err != nil {
        return err
    }
    return n.host.Connect(
        ctx,
        peer.AddrInfo{
            ID: pid,
            Addrs: []ma.Multiaddr{relayCircuit},
        },
    )
}

func (n *nodeRuntime) connectionCounts(pid peer.ID) (int, int) {
    if pid == "" {
        return 0, 0
    }
    direct := 0
    relay := 0
    for _, conn := range n.host.Network().ConnsToPeer(pid) {
        if conn.Stat().Limited {
            relay++
        } else {
            direct++
        }
    }
    return direct, relay
}

func (n *nodeRuntime) pathForPeer(pid peer.ID) string {
    if pid == "" {
        return "unavailable"
    }
    conns := n.host.Network().ConnsToPeer(pid)
    if len(conns) == 0 {
        return "unavailable"
    }
    for _, conn := range conns {
        if !conn.Stat().Limited {
            return "direct"
        }
    }
    return "relay"
}

func (n *nodeRuntime) closeForwards() {
    n.mu.Lock()
    defer n.mu.Unlock()
    for key, runtime := range n.forwards {
        runtime.stopOnce.Do(func() { close(runtime.stop) })
        _ = runtime.listener.Close()
        delete(n.forwards, key)
    }
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
    w.Header().Set("Content-Type", "application/json; charset=utf-8")
    w.Header().Set("Cache-Control", "no-store")
    w.WriteHeader(status)
    _ = json.NewEncoder(w).Encode(payload)
}
