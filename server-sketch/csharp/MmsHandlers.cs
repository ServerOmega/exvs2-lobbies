// SKETCH ONLY - MediatR handlers for the 5 MMS requests the game sends.
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using nue.protocol.mms;

namespace Server.Handlers.Mms;

public record MmsPingCommand(Request Request) : IRequest<Response>;
public record IssueNodeIdCommand(Request Request) : IRequest<Response>;
public record EntryMatchingCommand(Request Request) : IRequest<Response>;
public record CheckMatchingCommand(Request Request) : IRequest<Response>;
public record CancelMatchingCommand(Request Request) : IRequest<Response>;

public class MmsPingHandler : IRequestHandler<MmsPingCommand, Response>
{
    public Task<Response> Handle(MmsPingCommand c, CancellationToken ct) =>
        Task.FromResult(MmsReply.For(c.Request, ErrorCode.Success, r => r.ping = new Response.Ping()));
}

public class IssueNodeIdHandler : IRequestHandler<IssueNodeIdCommand, Response>
{
    private readonly INodeIdAllocator ids;
    public IssueNodeIdHandler(INodeIdAllocator ids) => this.ids = ids;

    public Task<Response> Handle(IssueNodeIdCommand c, CancellationToken ct)
    {
        // Game sends issue_count = 2 and rejects a reply with fewer node_ids (cmp @0x1407bc08f).
        // IDs must be globally unique: the client finds itself in CheckMatching by node_id equality.
        var count = (int)Math.Clamp(c.Request.issue_node_id?.IssueCount ?? 1u, 1u, 16u);
        var body = new Response.IssueNodeId();
        body.NodeIds.AddRange(ids.Take(count));
        return Task.FromResult(MmsReply.For(c.Request, ErrorCode.Success, r => r.issue_node_id = body));
    }
}

public class EntryMatchingHandler : IRequestHandler<EntryMatchingCommand, Response>
{
    private readonly Matchmaker mm;
    public EntryMatchingHandler(Matchmaker mm) => this.mm = mm;

    public Task<Response> Handle(EntryMatchingCommand c, CancellationToken ct)
    {
        var e = c.Request.entry_matching;
        if (e?.Myclient == null) return Task.FromResult(MmsReply.For(c.Request, ErrorCode.ErrRequest));
        var code = mm.Entry(e, DateTimeOffset.UtcNow);
        return Task.FromResult(MmsReply.For(c.Request, code, r => r.entry_matching = new Response.EntryMatching
        {
            PolingInterval = 3,          // seconds; game polls CheckMatching every poling_interval*1000 ms
            ApplyId = e.ApplyId,         // required by proto2 even though the game never reads it
        }));
    }
}

public class CheckMatchingHandler : IRequestHandler<CheckMatchingCommand, Response>
{
    private readonly Matchmaker mm;
    public CheckMatchingHandler(Matchmaker mm) => this.mm = mm;

    public Task<Response> Handle(CheckMatchingCommand c, CancellationToken ct)
    {
        var nodeId = c.Request.check_matching?.NodeId ?? 0;
        var (code, room, applyId) = mm.Check(nodeId, DateTimeOffset.UtcNow);
        var body = new Response.CheckMatching();
        if (room != null)
        {
            // room_id + ALL clients incl. the requester and CPU stand-ins; group_id = team (0/1).
            body.RoomId = room.RoomId;
            body.ApplyId = applyId;
            body.Clients.AddRange(room.Clients.Select(x => new Response.CheckMatching.MatchedClient
            {
                GroupId = x.GroupId, Client = x.Client,
            }));
        }
        // code 0 + empty clients => game keeps polling.
        return Task.FromResult(MmsReply.For(c.Request, code, r => r.check_matching = body));
    }
}

public class CancelMatchingHandler : IRequestHandler<CancelMatchingCommand, Response>
{
    private readonly Matchmaker mm;
    public CancelMatchingHandler(Matchmaker mm) => this.mm = mm;

    public Task<Response> Handle(CancelMatchingCommand c, CancellationToken ct)
    {
        mm.Cancel(c.Request.cancel_matching?.NodeId ?? 0);    // game ignores the reply
        return Task.FromResult(MmsReply.For(c.Request, ErrorCode.Success, r => r.cancel_matching = new Response.CancelMatching()));
    }
}
