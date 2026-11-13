// SKETCH ONLY - not compiled on the box (no dotnet there). Targets the Chiang-17 EXVS2-IB-Server layout
// (ASP.NET Core + MediatR + protobuf-net). Generate the mms types with protobuf-net's protogen from
// analysis/proto/from_exe/matchmaking_server_nue.proto (namespace nue.protocol.mms).
using System.IO;
using System.Threading.Tasks;
using MediatR;
using Microsoft.AspNetCore.Mvc;
using nue.protocol.mms;
using ProtoBuf;

namespace Server.Controllers;

[ApiController]
[Route("mms")]                       // RegisterPcb SRV_MATCH uri must be the FULL url: http://host:port/mms
public class MmsController : ControllerBase
{
    private readonly IMediator mediator;
    public MmsController(IMediator mediator) => this.mediator = mediator;

    [HttpPost]
    public async Task<IActionResult> Post()
    {
        using var ms = new MemoryStream();
        await Request.Body.CopyToAsync(ms);
        ms.Position = 0;

        Response response;
        try
        {
            var request = Serializer.Deserialize<Request>(ms);
            response = request.Type switch
            {
                MethodType.Ping            => await mediator.Send(new MmsPingCommand(request)),
                MethodType.IssueNodeId     => await mediator.Send(new IssueNodeIdCommand(request)),
                MethodType.EntryMatching   => await mediator.Send(new EntryMatchingCommand(request)),
                MethodType.CheckMatching   => await mediator.Send(new CheckMatchingCommand(request)),
                MethodType.CancelMatching  => await mediator.Send(new CancelMatchingCommand(request)),
                MethodType.MatchingSetting => MmsReply.For(request, ErrorCode.Success, r => r.matching_setting = new Response.MatchingSetting()),
                _                          => MmsReply.For(request, ErrorCode.ErrRequest),
            };
        }
        catch (ProtoException)
        {
            response = new Response { Type = MethodType.Ping, RequestId = "", Code = ErrorCode.ErrRequest };
        }

        // The game requires HTTP 200 for every reply (non-200 -> client error -1000) and a body that
        // parses with all proto2 required fields present (type, request_id, code, sub-message requireds).
        using var outMs = new MemoryStream();
        Serializer.Serialize(outMs, response);
        return File(outMs.ToArray(), "application/x-protobuf");
    }
}

public static class MmsReply
{
    // Always echo type + request_id.
    public static Response For(Request req, ErrorCode code, System.Action<Response>? fill = null)
    {
        var r = new Response { Type = req.Type, RequestId = req.RequestId ?? "", Code = code };
        fill?.Invoke(r);
        return r;
    }
}
