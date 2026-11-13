// SKETCH ONLY - in-memory 2v2 matchmaker (singleton). Mirrors server-sketch/python/mms_server.py,
// which is the tested reference implementation.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using nue.protocol.mms;

namespace Server.Handlers.Mms;

public interface INodeIdAllocator { IEnumerable<uint> Take(int count); }

/// Monotonic + persisted so ids never repeat across restarts.
public sealed class FileNodeIdAllocator : INodeIdAllocator
{
    private readonly object gate = new();
    private readonly string path;
    private uint next;
    public FileNodeIdAllocator(string path, uint start = 1000)
    {
        this.path = path;
        next = File.Exists(path) ? Math.Max(start, JsonSerializer.Deserialize<uint>(File.ReadAllText(path))) : start;
    }
    public IEnumerable<uint> Take(int count)
    {
        lock (gate)
        {
            var ids = Enumerable.Range(0, count).Select(i => next + (uint)i).ToArray();
            next += (uint)count;
            File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(next));
            File.Move(path + ".tmp", path, overwrite: true);
            return ids;
        }
    }
}

public sealed record RoomClient(uint GroupId, Client Client);
public sealed record Room(uint RoomId, IReadOnlyList<RoomClient> Clients, DateTimeOffset At);

public sealed class Team
{
    public const string NpcSerial = "PCB00000NPC";       // CPU partner the game puts in groups[0]
    public uint ApplyId; public List<Client> Clients = new(); public List<Player> Players = new();
    public (string Game, uint Version, uint World, long Lobby) Key;
    public HashSet<uint> BlAm = new(); public HashSet<string> BlLoc = new();
    public uint Timeout; public DateTimeOffset Created, LastSeen; public Room? Room;

    public static Team From(Request.EntryMatching e, DateTimeOffset now)
    {
        var t = new Team { ApplyId = e.ApplyId, Timeout = e.MatchingTimeout, Created = now, LastSeen = now };
        t.Clients.Add(e.Myclient); t.Players.Add(e.Myplayer);
        foreach (var g in e.Groups) { t.Clients.Add(g.Client); t.Players.Add(g.Player); }
        // attribute 1 = TestMode wanMatchingGroupId (only sent when a game feature flag is on) -> lobby key
        var lobby = e.Myplayer.Parameters.FirstOrDefault(p => p.AttributeId == 1)?.Parameter ?? 0;
        t.Key = (e.World?.MuchaGameId ?? "", e.World?.Version ?? 0, e.World?.WorldId ?? 0, lobby);
        t.BlAm.UnionWith(e.BlBanapassportAmIds); t.BlLoc.UnionWith(e.BlLocIds);
        return t;
    }
    public IEnumerable<Client> Humans => Clients.Where(c => c.PcbSerial != NpcSerial);
    public HashSet<uint> NodeIds => Humans.Select(c => c.NodeId).ToHashSet();
    public bool Compatible(Team o) =>
        Key == o.Key && !NodeIds.Overlaps(o.NodeIds)
        && !BlAm.Overlaps(o.Players.Select(p => p.BanapassportAmId)) && !o.BlAm.Overlaps(Players.Select(p => p.BanapassportAmId))
        && !BlLoc.Overlaps(o.Humans.Select(c => c.LocId)) && !o.BlLoc.Overlaps(Humans.Select(c => c.LocId));
}

public sealed class Matchmaker
{
    private readonly object gate = new();
    private readonly Dictionary<uint, Team> byNode = new();
    private readonly List<Team> queue = new();
    private uint nextRoom = 1;
    private static readonly TimeSpan Stale = TimeSpan.FromSeconds(20), Keep = TimeSpan.FromSeconds(60);

    public ErrorCode Entry(Request.EntryMatching e, DateTimeOffset now)
    {
        var t = Team.From(e, now);
        lock (gate)
        {
            Sweep(now);
            foreach (var n in t.NodeIds)
                if (byNode.TryGetValue(n, out var old) && old.Room == null)
                {
                    if (old.NodeIds.SetEquals(t.NodeIds)) { old.LastSeen = now; return ErrorCode.Success; } // partner re-sent same team
                    Drop(old);
                }
            foreach (var n in t.NodeIds) byNode[n] = t;
            queue.Add(t);
            TryMatch(now);
        }
        return ErrorCode.Success;
    }

    public (ErrorCode, Room?, uint) Check(uint nodeId, DateTimeOffset now)
    {
        lock (gate)
        {
            Sweep(now);
            if (!byNode.TryGetValue(nodeId, out var t)) return (ErrorCode.ErrMatchNoentry, null, 0);
            t.LastSeen = now;
            if (t.Room != null) return (ErrorCode.Success, t.Room, t.ApplyId);
            if (now - t.Created > TimeSpan.FromSeconds(t.Timeout)) { Drop(t); return (ErrorCode.MatchCanceled, null, 0); }
            return (ErrorCode.Success, null, 0);
        }
    }

    public void Cancel(uint nodeId)
    {
        lock (gate) if (byNode.TryGetValue(nodeId, out var t) && t.Room == null) Drop(t);
    }

    private void TryMatch(DateTimeOffset now)
    {
        for (var i = 0; i < queue.Count; i++)
            for (var j = i + 1; j < queue.Count; j++)
            {
                var a = queue[i]; var b = queue[j];
                if (!a.Compatible(b)) continue;
                var clients = a.Clients.Select(c => new RoomClient(0, c)).Concat(b.Clients.Select(c => new RoomClient(1, c))).ToList();
                a.Room = b.Room = new Room(nextRoom++, clients, now);
                queue.Remove(b); queue.Remove(a);
                i--; break;
            }
    }

    private void Drop(Team t)
    {
        queue.Remove(t);
        foreach (var k in byNode.Where(kv => kv.Value == t).Select(kv => kv.Key).ToList()) byNode.Remove(k);
    }

    private void Sweep(DateTimeOffset now)
    {
        foreach (var t in byNode.Values.Distinct().ToList())
            if ((t.Room == null && now - t.LastSeen > Stale + TimeSpan.FromSeconds(t.Timeout)) ||
                (t.Room != null && now - t.Room.At > Keep)) Drop(t);
    }
}
