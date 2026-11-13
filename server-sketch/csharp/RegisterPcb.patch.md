# RegisterPcb change (exvs game server, `nue.protocol.exvs`) — sketch

IB-Server today (per earlier decompile notes) returns roughly:

```csharp
ServerInfoes = { new ServerInfo { ServerType = ServerType.SrvMatch, Uri = $"{Host}/match", Port = 12345 } }
```

The game (`0x14076cd10`) uses `uri` **verbatim as the full URL** for SRV_MATCH and ignores `port`,
and it only starts online matching (STUN + IssueNodeId) when an **SRV_STUN** entry is present.
Change to:

```csharp
var mm = options.Value.Matchmaking;   // appsettings: see appsettings.Matchmaking.json
response.register_pcb.ServerInfoes.Clear();
response.register_pcb.ServerInfoes.Add(new Response.RegisterPcb.ServerInfo
{
    ServerType  = ServerType.SrvMatch,
    Uri         = mm.MatchUrl,          // e.g. "http://203.0.113.10:5000/mms"  (scheme+host+port+path)
    Port        = 0,                    // ignored by the game for MATCH
    AccountName = "", AccountPass = "", // fill only if these are proto2 'required' in your generated type
});
response.register_pcb.ServerInfoes.Add(new Response.RegisterPcb.ServerInfo
{
    ServerType  = ServerType.SrvStun,
    Uri         = mm.StunHost,          // plain IP literal is safest (DNS resolution not verified)
    Port        = mm.StunPort,          // 3478
    AccountName = mm.StunUser ?? "",    // used only if the STUN server answers 401/438 (long-term creds)
    AccountPass = mm.StunPass ?? "",
});
```

Leave `ipv4_flag = true`, `sram_clear`, maintenance fields as they are. Keep `lm_ip_addresses` empty
for online-only play (they are the Live Monitor addresses the cabinet reports to).

Program.cs wiring:

```csharp
builder.Services.AddSingleton<Matchmaker>();
builder.Services.AddSingleton<INodeIdAllocator>(_ => new FileNodeIdAllocator("mms_nodeids.json"));
// MediatR already scans the assembly in IB-Server; the new handlers are picked up automatically.
```
