---
name: understand-renderdoc-capture
description: Analyze an opened RenderDoc capture via the RenderDoc MCP to understand frame flow, pass structure, shader bindings, resource usage, and GPU timing. Use this skill whenever the user requests RenderDoc capture analysis, including frame overview, pass lookup, draw call investigation, texture/buffer tracking, shader parameters, or GPU bottlenecks. Use it even if the user does not explicitly say “analyze capture” but mentions render passes, draw calls, shaders, or RenderDoc.
---

# Understand RenderDoc Captures

## Core Principles

**Start broad, then zoom in.** Begin with frame summary and pass structure before inspecting individual actions.

**Top-level markers are only a starting point.** They are often too coarse to represent full pass structure. Use `get_draw_calls` to expand the hierarchy; avoid `include_children=false` except for narrow queries.

**`event_id` must come from real data.** Never guess. Obtain IDs from `get_frame_summary` or `get_draw_calls`, then use them with `get_action_details`, `get_shader_details`, `get_pipeline_state`, and related tools.

**Use `marker_filter` to locate passes.** Reserve `event_id_min/max` for strict ranges or when no marker exists; avoid unfiltered full-action scans.

**`resource_id` connects tools.** It appears in outputs/depth targets, pipeline state RTs, and shader SRVs/UAVs, and feeds into `get_texture_info`, `find_draws_by_resource`, and related queries.

**Resource IDs look like `ResourceId::123`.** `find_draws_by_resource` also accepts plain numbers like `"123"`.

---

## Tool Quick Guide

| Goal | Tool |
|------|------|
| Check capture loaded | `get_capture_status` |
| Frame overview + stats | `get_frame_summary` |
| Browse/filter draw calls | `get_draw_calls` |
| Inspect action IO + shader summary | `get_action_details` |
| IA/Viewport/RT/Depth bindings | `get_pipeline_state` |
| Shader source, CB values, SRV/UAV | `get_shader_details` |
| Texture metadata | `get_texture_info` |
| Read texture/buffer data | `get_texture_data` / `get_buffer_contents` |
| Find draws using a texture/resource | `find_draws_by_texture` / `find_draws_by_resource` |
| GPU timing hotspots | `get_action_timings` |

---

## Key Tool Notes

### `get_capture_status`
Confirms whether a capture is loaded and returns `api` and `filename`. If `loaded: false`, instruct the user to open a capture in RenderDoc.

### `get_frame_summary`
Should be the first step for any capture:
- `top_level_markers`: top-level pass list with `name`, `event_id` (pass start), `child_count`. **All range-based filtering depends on these IDs.**
- `statistics`: counts of `draw_calls`, `dispatches`, `clears`, `copies`, `presents`, `markers`.
- `resource_counts`: totals for `textures` and `buffers`.

### `get_draw_calls`
Gets the action hierarchy with flexible filters:

| Params | Use |
|--------|-----|
| `only_markers=true, include_children=true` | Quick list of all pass names |
| `marker_filter="Shadow", only_actions=true` | All draw calls inside Shadow pass |
| `event_id_min=N, event_id_max=M` | Slice by ID range (from `get_frame_summary`) |
| `flags_filter=["Dispatch"], only_actions=true` | Compute dispatch only |
| `flags_filter=["Drawcall"], only_actions=true` | Draw calls only |

Return fields: `event_id`, `name`, `flags`. Draw calls include `num_indices`, `num_instances`; dispatches include `dispatch_dimension [x,y,z]`.

**Common flags:** `Drawcall`, `Indexed`, `Instanced`, `Dispatch`, `Clear`, `Copy`, `Present`, `Indirect`.

### `get_action_details(event_id)`
Detailed info for one action:
- **Drawcall**: `outputs` (RT resource IDs), `depth_output`, shader summaries (`vertex_shader`/`pixel_shader`).
- **Dispatch**: `dispatch_dimension [x,y,z]`, `compute_shader` summary.
- **Copy**: `copy_source` / `copy_destination` with subresource info.

> Summaries include basic `srv`/`uav`/`constant_buffers`. Use `get_shader_details` for full bindings or CB values.

### `get_pipeline_state(event_id)`
Only for draw calls. Returns:
- `input_assembly`: `topology`, `index_buffer`, `vertex_buffers`.
- `viewports`: `width`, `height`, `min_depth`, `max_depth` (render resolution check).
- `render_targets`: RT resource IDs; `depth_target`: depth resource ID.

> Shader resource bindings are **not** included (see `get_shader_details`).

### `get_shader_details(event_id, stage)`
`stage` = `vertex` / `hull` / `domain` / `geometry` / `pixel` / `compute`

Returns:
- With source: `source_files` (filename + contents), `entry_source_name`
- Without source: `disassembly`, `entry_point`
- `constant_buffers`: `name`, `byte_size`, and `data` map (variable → `{value, type}`)
- `srv`: `shader_name`, `resource`, `descriptor_type`, `format`, `texture_type`
- `uav`: same as `srv`

### `get_texture_info(resource_id)` / `get_texture_data(...)` / `get_buffer_contents(...)`
- `get_texture_info`: `width`, `height`, `format`, `mip_levels`, `dimension`, `msaa_samples`
- `get_texture_data`: Base64 pixel data with `mip`/`slice`/`sample`. Cube map slices: 0–5 (X+, X-, Y+, Y-, Z+, Z-). 3D textures can use `depth_slice`.
- `get_buffer_contents`: Base64 bytes; use `offset`+`length` to slice; `total_size` is full size.

### `find_draws_by_texture(name)` / `find_draws_by_resource(resource_id)`
Find draws using a resource. Returns `matches` with `event_id`, `name`, `match_reason`.

### `get_action_timings()`
GPU timings (requires support). Returns `timings` (`event_id`, `name`, `duration_ms`) and `total_duration_ms`. Supports `marker_filter` to narrow scope.

---

## Analysis Templates

Select the appropriate path for the question; avoid running all steps indiscriminately.

### Path 1: Frame overview
```
get_capture_status → get_frame_summary → get_draw_calls(only_markers)
```
Summarize pass order and high-level structure from `top_level_markers`.

### Path 2: Deep-dive a pass
```
get_frame_summary or get_draw_calls(only_markers)
→ get_draw_calls(marker_filter=<pass>, only_actions=true)
→ get_action_details(event_id)
→ get_shader_details(event_id, stage)
→ get_pipeline_state(event_id)
```

### Path 3: Track a texture/resource lifecycle
```
get_shader_details(known event_id, stage)
→ find target in srv/uav (shader_name + resource_id)
→ find_draws_by_texture(texture_name) or find_draws_by_resource(resource_id)
→ use match_reason to separate writes vs reads
→ get_action_details(writer event_id)
→ get_texture_info(resource_id)
→ get_shader_details(reader event_id, stage)
```

### Path 4: GPU hotspot analysis
```
get_action_timings(marker_filter=...)
→ sort by duration_ms
→ get_action_details(event_id)
→ get_shader_details(event_id, "pixel")
→ get_pipeline_state(event_id)
```

### Path 5: Compute shader analysis
```
get_draw_calls(flags_filter=["Dispatch"], only_actions=true)
→ get_action_details(event_id)
→ get_shader_details(event_id, "compute")
```