#!/bin/bash
# Runs once, automatically, on the container's first boot — placed in
# /docker-entrypoint-initdb.d/ by docker/Dockerfile, which the base image's
# own entrypoint (/docker-entrypoint.sh) executes after IRIS itself has
# finished starting and its own first-init steps (namespace/user setup) are
# done. See docs/docker.md for the full chain and how this was verified.
#
# Compiles the ISOE.* classes (staged into the image by the Dockerfile) and
# creates the /api/health and /api/ai web applications via the documented
# Security.Applications ObjectScript API — the same one this project's own
# Web Applications page exercises via REST, used directly here since no
# authenticated HTTP session exists yet this early in boot.
set -e

echo "IRIS Command Center: unexpiring default passwords, compiling ISOE classes, creating web applications..."

iris session "$ISC_PACKAGE_INSTANCENAME" -U%SYS <<'EOSESS'
do ##class(Security.Users).UnExpireUserPasswords("*")

; The web applications below are configured with NameSpace="USER", so the
; ISOE.* classes must be COMPILED into USER too -- confirmed live that
; compiling them while connected to %SYS (this session's default) puts them
; in %SYS instead, where USER's web dispatch can never find them: every
; request 404s (IRIS's private webserver still creates a CSP session and
; cookie for the app, but %CSP.REST's route table lookup silently fails to
; find a class by that name in USER, producing the same plain-text 404 a
; genuinely unmatched route would).
zn "USER"

set sc = $system.OBJ.Load("/opt/iris-command-center/classes/ISOE/HealthAnalyzer.cls", "ck")
set sc = $system.OBJ.Load("/opt/iris-command-center/classes/ISOE/HealthAnalyzerREST.cls", "ck")
set sc = $system.OBJ.Load("/opt/iris-command-center/classes/ISOE/AskIris.cls", "ck")
set sc = $system.OBJ.Load("/opt/iris-command-center/classes/ISOE/AskIrisREST.cls", "ck")

; Security.Applications is %SYS-only -- confirmed live it raises <CLASS DOES
; NOT EXIST> when called from USER, so switch back before using it. (The
; web app's own NameSpace="USER" property, set below, is what makes the
; *app* run against USER -- Security.Applications itself must be called
; from %SYS regardless of that.)
zn "%SYS"

; Multi-line `if cond { ... }` blocks parse fine in an interactive terminal
; but do NOT survive being piped through a heredoc to `iris session` non-
; interactively (confirmed live: produces a <SYNTAX> error on the closing
; brace) -- each line here must be a complete, single-line statement.
kill prop
set prop("AutheEnabled") = 32
set prop("NameSpace") = "USER"
set prop("DispatchClass") = "ISOE.HealthAnalyzerREST"
set prop("Description") = "HealthAnalyzer -- Embedded Python bonus feature"
do:'##class(Security.Applications).Exists("/api/health") ##class(Security.Applications).Create("/api/health", .prop)

kill prop
set prop("AutheEnabled") = 32
set prop("NameSpace") = "USER"
set prop("DispatchClass") = "ISOE.AskIrisREST"
set prop("Description") = "Ask IRIS -- Vector Search + LangChain bonus feature"
do:'##class(Security.Applications).Exists("/api/ai") ##class(Security.Applications).Create("/api/ai", .prop)

halt
EOSESS

echo "IRIS Command Center: done."
echo "  - Dashboard/Health Report will show a real score immediately (Embedded Python + psutil)."
echo "  - Ask IRIS needs an OpenAI API key: create a wallet secret named AskIris.OpenAIApiKey"
echo "    on the Wallets page, then click Rebuild index on the Ask IRIS page. See docs/ask-iris.md."
