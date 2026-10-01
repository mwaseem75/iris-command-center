#!/bin/sh
# iris-2 only. Runs once IRIS has started, on EVERY container start
# (docker-compose.yml passes it to /iris-main as its --after command).
#
# Sets the iris-2 password (the iris_2_password Compose secret, from
# IRIS2_PASSWORD in .env) on the predefined _SYSTEM, SuperUser and Admin
# accounts, and clears their "change password" / expiry flags. The password
# is read by ObjectScript from the secret file, so it never appears on a
# command line or in the output. Repeating it is safe, and changing
# IRIS2_PASSWORD takes effect on the next start.
#
# CSPSystem is left alone: the web gateway logs in with it.
#
# A failure is logged but never stops IRIS.

SECRET=/run/secrets/iris_2_password

if [ ! -s "$SECRET" ]; then
  echo "WARNING: iris-2 password secret is missing or empty; the predefined accounts keep their current passwords"
  exit 0
fi

iris session IRIS -U %SYS <<'EOF' | tr -d '\r' | grep '^CC:' \
  || echo "WARNING: could not set the iris-2 password"
set s=##class(%Stream.FileCharacter).%New(),sc=s.LinkToFile("/run/secrets/iris_2_password"),pw=$zstrip(s.ReadLine(),"<>WC") kill s
if pw="" { write "CC: empty password, nothing changed",! } else { for u="_SYSTEM","SuperUser","Admin" { kill p set p("Password")=pw,p("ChangePassword")=0,p("PasswordNeverExpires")=1,sc=##class(Security.Users).Modify(u,.p) write "CC: ",u," ",$select(sc=1:"password set",1:"failed"),! } }
kill pw,p
halt
EOF

exit 0
