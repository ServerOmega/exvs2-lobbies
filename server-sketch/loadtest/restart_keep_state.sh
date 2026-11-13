#!/bin/bash
# restart the C# server, KEEPING its DB and node-id state file (in-memory matchmaker state is lost)
pkill -f Server-Infinite.dll; sleep 1
cd "${SERVER_DIR:-.}" && export PATH=$HOME/.dotnet:$PATH
CardServerConfig__OnlineMatching__Enabled=true setsid nohup dotnet Server-Infinite.dll >> server.log 2>&1 < /dev/null &
for i in $(seq 40); do curl -s -o /dev/null http://127.0.0.1:28080/ && break; sleep 0.5; done
