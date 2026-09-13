# Linux / Proton / RTX 50 validation notes

Findings from an extended test session: 007 First Light (Streamline-based DX12 title), Ubuntu,
RTX 5070 (Blackwell), driver 615.71.09 (Linux R615 branch; equivalent to Windows 616.92 - the two
platforms number the same branch differently, so check the branch, not the raw number, against
this fork's stated 616.56 minimum). Proton 11.0 and Proton Experimental both tested.

## OptiScaler vs. a from-scratch NGX-forwarder addon: same runtime, different outcome

A separate NR host - a ReShade add-on driving `nvngx_dlssnr.dll` 310.8 through a hand-written NGX
forwarder - reliably reproduced Xid 31 (`FAULT_PDE`, `ACCESS_TYPE_VIRT_READ`) on this exact
GPU/driver/game combination: 17 confirmed occurrences, the fault address never moved by a single
bit across four independent fix attempts (NGX FrameGen-handle tracking, descriptor-heap shadowing,
a from-source ReShade patch, a custom vkd3d-proton build). A clean negative control - the addon
removed, everything else unchanged - ran a full session with no fault, isolating the addon's own
evaluation path as the trigger.

Swapping to this fork as the sole NR host, same `nvngx_dlssnr.dll` 310.8, same driver, same GPU:
zero Xid 31 across every subsequent test. This is comparative evidence the original fault lived in
that addon's resource/evaluation contract, not in the NR runtime itself - useful if anyone else
lands here from the same symptom.

## The game's own native Streamline FG plugin crashes on its own

Independent of any of the above: the game's own `sl.dlss_g.dll` (its native Streamline Frame
Generation plugin) produced Xid 32 (invalid/corrupted push-buffer stream), then on a later run
Xid 13 + Xid 32 together, within seconds of launch - **before DLSS-NR was ever enabled and before
any Frame Generation toggle was touched**. Both crashes coincided with the plugin's own repeated
`cloneFakeBuffers`/fullscreen-state churn during Streamline's plugin-manager init - the game's
own FG negotiation, not anything OptiScaler does. `[FrameGen] Enabled=false` in `OptiScaler.ini`
does not prevent this: that key only gates OptiScaler's *own* FG implementation, not the game's
native Streamline FG negotiation, which happens regardless.

**Removing `sl.dlss_g.dll` from the game's own directory** (leaving the rest of its native
Streamline set - `sl.common.dll`, `sl.dlss.dll`, `sl.dlss_d.dll`, `sl.interposer.dll`, `sl.nis.dll`,
`sl.pcl.dll`, `sl.reflex.dll` - untouched) fully resolved it: zero further Xid faults across every
subsequent NR-enabled session. If a game hangs or Xid-faults on launch before you've touched any
NR or FG setting, check whether its own Streamline FG plugin is present and try removing it before
suspecting OptiScaler.

Upgrading the remaining native Streamline plugins from the game's stock 2.13.0 to the official
2.14.1 SDK release worked without incident for SR + NR.

## Native NVIDIA Frame Generation does not work under DXVK-NVAPI here

Tested two paths: the game's own native Streamline FG (after temporarily restoring
`sl.dlss_g.dll` in isolation to confirm this specifically, then removing it again) and OptiScaler's
own `[FrameGen] FGOutput=dlssg` (using a private Streamline 2.14.1 copy under
`OptiScaler/streamline/`, keeping the game's own copy absent). Both produce a dark/black output,
not a crash - no Xid fault in either case.

Root cause, from the log: `NvAPI_D3D_SetReflexSync(...)` returns error `-3` (not-implemented
class), and Streamline retries in a tight loop, logging `RSYNC: setDynamicMFGParams failed with
status 1` and `RSYNC: setReflexTiming failed with status 1` dozens of times per second. DXVK-NVAPI
does not implement the Reflex-sync surface that Streamline's Dynamic Multi-Frame-Generation
negotiation depends on for pacing, on this stack. This is a platform-layer gap below either
injection path - it reproduces identically whether the `sl.dlss_g.dll` plugin loads from the game's
own folder or from OptiScaler's private `OptiScaler/streamline/` copy, since both go through the
same DXVK-NVAPI shim. Choosing a different plugin location does not route around it.

Not attempted here, but worth trying based on other users' reports in this project's discussions:
FSR-FG or XeFG through OptiScaler's own FG (`FGOutput=fsrfg` / `xefg`) instead of `dlssg` - neither
depends on the same NVIDIA Reflex-sync path.

## ReversibleMode was undiscoverable

`DlssNrReversibleMode` has existed in `Config.h` since the hybrid-proxy commits (7ffcf8ee,
76fce1b4) and the shader already implements all five modes, but the ini key was never added to the
shipped template - it silently sat at its default (0, soft-knee) with no way to discover modes 3/4
short of reading the source. Mode 3 (hybrid + composed) measurably improved highlight detail
recovery without the midtone cost of mode 1, in this testing. Documented in the ini template as
part of this PR.
