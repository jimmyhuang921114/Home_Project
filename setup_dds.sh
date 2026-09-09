#!/usr/bin/env bash

IFACE="wlp130s0f0"
THOR_HOST="192.168.0.233"

JIMMY_IP=$(
  ip -4 -o addr show dev "$IFACE" 2>/dev/null \
  | awk '{print $4}' \
  | cut -d/ -f1 \
  | head -1
)

if [ -z "$JIMMY_IP" ]; then
  echo "DDS_SETUP=FAIL"
  echo "REASON=no IPv4 on $IFACE"
  return 1 2>/dev/null || exit 1
fi

mkdir -p "$HOME/.ros"

cat > "$HOME/.ros/cyclonedds.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain Id="any">
    <General>
      <Interfaces>
        <NetworkInterface
          name="$IFACE"
          priority="default"/>
      </Interfaces>
      <AllowMulticast>spdp</AllowMulticast>
    </General>

    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
      <Peers>
        <Peer Address="$THOR_HOST"/>
      </Peers>
    </Discovery>

    <Tracing>
      <Verbosity>warning</Verbosity>
      <OutputFile>stderr</OutputFile>
    </Tracing>
  </Domain>
</CycloneDDS>
XML

export ROS_DOMAIN_ID=40
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$HOME/.ros/cyclonedds.xml"

echo "DDS_SETUP=PASS"
echo "LOCAL_INTERFACE=$IFACE"
echo "LOCAL_IP=$JIMMY_IP"
echo "THOR_PEER=$THOR_HOST"
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
echo "CYCLONEDDS_URI=$CYCLONEDDS_URI"
