# Sidecar fixtures (beta preview, unverified on hardware)
Shape source: dcan999/Sidecar-Beta README.md blob 6cfdc4b1 line 27 (T to head T//4, lane T%4+1);
host/pi/runtime/sc_watchd.py blob c1e93fb4 lines 9-11 and 255-275 (G-code markers);
host/pi/ui/source/src/lib/sidecarApi.ts blob 6d9823fc lines 123-165 (load-cell lanes shape; client error shape
`{ok:false,error,_http}`). The Pi API's `state` and `lane-meta` reply bodies are not visible in the client, so those
fixtures hold only `{ok:true}` and the adapter reports every field unknown. The project's own STATUS.md says the
stock-U1 handoff and controller builds are not validated on hardware. Written by hand; not captured from a device.
Evidence label: fixture-tested.
