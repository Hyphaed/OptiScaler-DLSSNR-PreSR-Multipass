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

**Update: FSR-FG through OptiScaler also fails on this game, via a different root cause.** Tested
`FGInput=dlssg` + `FGOutput=fsrfg` (with `amd_fidelityfx_loader_dx12.dll` and
`amd_fidelityfx_framegeneration_dx12.dll` present) specifically to avoid the Reflex-Sync path
above - it doesn't depend on the same NVIDIA API surface, and other users in this project's
discussions reported it working where DLSS-FG didn't. Here it produced Xid 13 (Graphics
Exception) and a hung process ~9 seconds after launch. The log shows the actual mechanism:
repeated `Streamline supports only one DXGISwapChain (...). Skipping some Present() hooks for
DXGISwapChain (...)` warnings, immediately followed by `vkQueueSubmit error: FFFFFFFC`
(`VK_ERROR_DEVICE_LOST`) specifically inside OptiScaler's own `MenuOverlayVk` - a dual-swapchain /
Vulkan-interop conflict between the FFX FG bridge and OptiScaler's own overlay renderer, unrelated
to Streamline or Reflex-Sync entirely. Confirmed against NVIDIA's own published Vulkan Reflex SDK
(`NvLowLatencyVk.h`) that no Reflex-Sync/Dynamic-MFG function is published in the public API at
all - not merely unimplemented, there's no documented hook to build one against. Filed as
[vkd3d-proton#3292](https://github.com/HansKristian-Work/vkd3d-proton/issues/3292) rather than
ship a speculative patch against undocumented driver-internal behaviour.

Not attempted: XeFG (`FGOutput=xefg`) - a third, separate FG technology this fork supports that
also doesn't depend on Reflex-Sync. Given FSR-FG's failure was an overlay/swapchain conflict
rather than anything FSR-specific, XeFG may hit the same conflict, or may not - worth testing
before concluding no FG technology works here.

## Forcing DLSS-RR on a game with no in-menu RR option: fails safely, not a usable path

This game's engine never calls `NVSDK_NGX_D3D12_CreateFeature` with
`NVSDK_NGX_Feature_RayReconstruction` - only `SuperSampling` - so its graphics menu has no Ray
Reconstruction toggle. `TryCreateOptiFeature` (`inputs/NVNGX_DLSS_Dx12.cpp`) picks the upscaler
backend for a `SuperSampling` call from `[Upscalers] Dx12Upscaler` regardless of which NGX feature
the game actually requested, so setting `Dx12Upscaler=dlssd` does substitute a real DLSSD (RR)
feature for the game's SR request, bypassing the missing menu option.

Tested it. `DLSSD::Init` fails immediately and OptiScaler falls back to FSR 2.1.2 as the base
upscaler (`Feature 'DLSSD' initialization failed falling back to FSR 2.1.2`) - no crash, no Xid,
the fallback path itself works correctly. Root cause: DLSS-RR's NGX contract needs G-buffer
signals SR does not (`DLSS.Input.DiffuseAlbedo`, `SpecularAlbedo`, `GBuffer.Normals`,
`GBuffer.Roughness`, `MotionVectorsReflection`, plus specular/diffuse hit-distance buffers) - a
game whose engine never intends to call the RR feature has no reason to ever populate those NGX
parameters, so `DLSSD::Init` fails against its own contract. The resulting FSR 2.1.2 + NR
combination is a quality *downgrade* from DLSS + NR, not an upgrade - any FPS or stability
improvement observed here is explained entirely by FSR 2.1.2 being cheaper than DLSS, not by
Ray Reconstruction doing anything.

Not something OptiScaler can safely paper over with a config default: it would need to detect,
before substituting DLSSD, whether the game's NGX parameter set actually contains the G-buffer
inputs RR requires, and refuse the substitution (or synthesize safe defaults) when it doesn't.
Flagging as a real gap rather than shipping a change against it.

## Multipass (`Passes=2`) reintroduces grain and costs ~30% FPS at default tuning

Upstream PR #43 (interpass raw-output clamp fix) was believed to be the blocker for testing
`Passes>1` safely. It is not: this fork's current tree already implements the equivalent fix
independently, for both DX12 and Vulkan (`DlssNr_Dx12_Run.cpp`'s `passClamp`/
`DlssNrMode_ClampProxy`, `DlssNrFeature_Vk.cpp`'s `state.passClamp`), landed as part of the
refactor that split the old monolithic `DlssNr_Dx12.cpp` into the current per-concern files. PR
#43's diff no longer applies (its base predates that split by ~18k lines in this directory alone)
and is not worth porting - the fix it proposes is already present under a different, more complete
implementation.

Tested `Passes=2` anyway, since the presumed blocker was gone. Measured via MangoHud, not felt:
median FPS dropped from 88-89 (`Passes=1`) to 61.8 (p1_low 49.9) - about -30%, matching this
project's own ini documentation ("2 and 3... cost almost exactly 2x and 3x the model time").
Grain also visibly returned to the image.

Root cause: `OptiScaler/dlssnr/PassProfiles.h` defaults pass 2 and pass 3 to
`intensity=1.0`/`structure=1.0`, inherited from pass 1's own config, unless a per-pass override
(`DlssNrPass2Intensity`, etc.) is set. The same full-strength detail-injection operator that
already ran once therefore reapplies at full gain to its own already-processed output - not new
information, the same operator twice. This matches the general finding in iterative
super-resolution/refinement work (e.g. SR3, "Image Super-Resolution via Iterative Refinement",
arXiv:2104.07636): iteration count and per-iteration strength need to be balanced against noise
amplification, or repeated refinement compounds high-frequency artifacts instead of improving the
image. This project's own ini already calls multipass "deliberately over-processed" - the grain is
that tradeoff surfacing, not a new bug.

Not fully closed: damping pass 2 via `DlssNrPass2Intensity`/`DlssNrPass2LocalStructure` below 1.0
(a light reinforcement rather than a full reapplication) is a plausible follow-up this fork
already exposes and this session did not test. `Passes=1` is the deployed config until that's
tried.

## ReversibleMode was undiscoverable

`DlssNrReversibleMode` has existed in `Config.h` since the hybrid-proxy commits (7ffcf8ee,
76fce1b4) and the shader already implements all five modes, but the ini key was never added to the
shipped template - it silently sat at its default (0, soft-knee) with no way to discover modes 3/4
short of reading the source. Mode 3 (hybrid + composed) measurably improved highlight detail
recovery without the midtone cost of mode 1, in this testing. Documented in the ini template as
part of this PR.
