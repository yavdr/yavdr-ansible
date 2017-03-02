  #!/usr/bin/env python3
  # This script sends a multicast message and awaits responses by Sat>IP servers.
  # returns the boolean variable 'satip_detected' as json
  import json
  import socket
  import sys
  import time

  SSDP_ADDR = "239.255.255.250"
  SSDP_PORT = 1900
  # SSDP_MX = max delay for server response
  # a value of 2s is recommended by the SAT>IP specification 1.2.2
  SSDP_MX = 2
  SSDP_ST = "urn:ses-com:device:SatIPServer:1"

  ssdpRequest = "\r\n".join((
      "M-SEARCH * HTTP/1.1",
      "HOST: %s:%d" % (SSDP_ADDR, SSDP_PORT),
      "MAN: \"ssdp:discover\"",
      "MX: %d" % (SSDP_MX),
      "ST: %s" % (SSDP_ST),
      "\r\n"))

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  # according to Sat>IP Specification 1.2.2, p. 20
  # a client should send three requests within 100 ms with a ttl of 2
  sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
  sock.settimeout(SSDP_MX + 0.5)
  for _ in range(3):
      sock.sendto(ssdpRequest.encode('ascii'), (SSDP_ADDR, SSDP_PORT))
      time.sleep(0.03)
  try:
      response = sock.recv(1000).decode()
      if response and "SERVER:" in response:
          got_response = True
      else:
          raise ValueError('No satip server detected')
  except (socket.timeout, ValueError):
      got_response = False
  finally:
      print(json.dumps(
          {'satip_detected': got_response}
      ))
