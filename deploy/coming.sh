#!/usr/bin/env bash
# The note that a new build is on its way (monet/app.py: coming), kept on the droplet in /opt/monet/data/coming.json.
# The canvas counts down to it; the server clears it when that build comes up.
#   deploy/coming.sh user@host testing     a push started its run: the note, from now (the droplet's clock)
#   deploy/coming.sh user@host building    its tests passed: the same note, the clock running on (or a new one)
#   deploy/coming.sh user@host gone        it is not coming (a test failed, the deploy broke): taken back, if it is this build's
set -uo pipefail
HOST="${1:?usage: coming.sh user@host testing|building|gone}"
WHAT="${2:?testing, building or gone}"
COMMIT="${COMMIT:-$(git rev-parse --short HEAD)}"
F=/opt/monet/data/coming.json
case "$WHAT" in
  testing)  CMD="printf '{\"commit\": \"%s\", \"since\": %s, \"whole\": true, \"stage\": \"testing\"}\n' $COMMIT \$(date +%s) > $F" ;;
  # the note of this build is kept with its clock; where there is none (it could not be left), one is left now
  building) CMD="if grep -qs '\"$COMMIT\"' $F; then sed -i 's/\"stage\": \"testing\"/\"stage\": \"building\"/' $F; else printf '{\"commit\": \"%s\", \"since\": %s}\n' $COMMIT \$(date +%s) > $F; fi" ;;
  gone)     CMD="grep -qs '\"$COMMIT\"' $F && rm -f $F; true" ;;
  *) echo "testing, building or gone"; exit 2 ;;
esac
# the port is knocked on all day: ask again rather than fail on a dropped connection
for try in $(seq 1 10); do ssh -o ConnectTimeout=20 "$HOST" "$CMD" && exit 0; sleep 4; done
echo "::warning::could not ${WHAT/gone/take back} the note that a build is coming"
exit 0
