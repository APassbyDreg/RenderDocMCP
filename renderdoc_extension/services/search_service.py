"""
Reverse lookup search service for RenderDoc.
"""

import renderdoc as rd

import time

from ..utils import Parsers, Helpers, logger


class SearchService:
    """Reverse lookup search service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def _search_draws(self, matcher_fn):
        """
        Common template for searching draw calls.

        Args:
            matcher_fn: Function(pipe, controller, action, ctx) -> match_reason or None
        """
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        raise RuntimeError(
            "_search_draws is deprecated and should not be used. Use ActionService.find_draws_by_texture/resource instead.")

        result = {"matches": [], "scanned_draws": 0}

        def callback(controller):
            root_actions = controller.GetRootActions()
            structured_file = controller.GetStructuredFile()
            all_actions = Helpers.flatten_actions(root_actions)

            # Filter to only draw calls and dispatches
            draw_actions = [
                a for a in all_actions
                if a.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch)
            ]
            result["scanned_draws"] = len(draw_actions)

            logger.info("Searching %d draw calls..." % len(draw_actions))
            t_start = time.time()

            for i, action in enumerate(draw_actions):
                controller.SetFrameEvent(action.eventId, False)
                pipe = controller.GetPipelineState()

                logger.debug(
                    f"- Checking event {action.eventId} ({i + 1}/{len(draw_actions)}): {action.GetName(structured_file)}")

                match_reason = matcher_fn(pipe, controller, action, self.ctx)
                if match_reason:
                    result["matches"].append({
                        "event_id": action.eventId,
                        "name": action.GetName(structured_file),
                        "match_reason": match_reason,
                    })

            logger.info("Search completed in %.2f seconds. Found %d matches out of %d draw calls." % (
                time.time() -
                t_start, len(result["matches"]), result["scanned_draws"]
            ))

        self._invoke(callback)
        result["total_matches"] = len(result["matches"])
        return result

    def _format_resource_usage(self, usage, ctx):
        """Format resource usage into a readable reason string."""
        usage_enum = usage.usage
        reason = None

        for stage in Helpers.get_all_shader_stages():
            if usage_enum == rd.ResUsage(stage):
                reason = "%s SRV" % str(stage)
                break
            if usage_enum == rd.RWResUsage(stage):
                reason = "%s UAV" % str(stage)
                break
            if usage_enum == rd.CBUsage(stage):
                reason = "%s ConstantBuffer" % str(stage)
                break

        if reason is None:
            usage_label = str(usage_enum)
            if usage_label.startswith("ResourceUsage."):
                usage_label = usage_label.split(".", 1)[1]
            reason = usage_label

        if usage.view != rd.ResourceId.Null():
            view_name = ""
            try:
                view_name = ctx.GetResourceName(usage.view)
            except Exception:
                pass
            if view_name:
                reason = "%s (view: %s)" % (reason, view_name)

        return reason

    def find_draws_by_shader(self, shader_name, stage=None):
        """Find all draw calls using a shader with the given name (partial match)."""
        # Determine which stages to check
        if stage:
            stages_to_check = [Parsers.parse_stage(stage)]
        else:
            stages_to_check = Helpers.get_all_shader_stages()

        def matcher(pipe, controller, action, ctx):
            for s in stages_to_check:
                shader = pipe.GetShader(s)
                if shader == rd.ResourceId.Null():
                    continue

                reflection = pipe.GetShaderReflection(s)
                if reflection:
                    entry_point = pipe.GetShaderEntryPoint(s)
                    shader_debug_name = ""
                    try:
                        shader_debug_name = ctx.GetResourceName(shader)
                    except Exception:
                        pass

                    if shader_name.lower() in entry_point.lower():
                        return "%s entry_point: '%s'" % (str(s), entry_point)
                    elif shader_debug_name and shader_name.lower() in shader_debug_name.lower():
                        return "%s name: '%s'" % (str(s), shader_debug_name)
            return None

        return self._search_draws(matcher)

    def find_draws_by_texture(self, texture_name):
        """Find all draw calls using a texture with the given name (partial match)."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"matches": [], "scanned_draws": 0}
        texture_name_lower = texture_name.lower()

        def callback(controller):
            structured_file = controller.GetStructuredFile()
            matching_textures = []

            for tex in controller.GetTextures():
                res_name = ""
                try:
                    res_name = self.ctx.GetResourceName(tex.resourceId)
                except Exception:
                    pass
                if res_name and texture_name_lower in res_name.lower():
                    matching_textures.append((tex.resourceId, res_name))

            matches_by_event = {}
            for resource_id, res_name in matching_textures:
                for usage in controller.GetUsage(resource_id):
                    if usage.eventId == 0:
                        continue

                    action = self.ctx.GetAction(usage.eventId)
                    if not action:
                        continue

                    if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch)):
                        continue

                    usage_reason = self._format_resource_usage(usage, self.ctx)
                    reason = "%s: %s" % (res_name, usage_reason)
                    entry = matches_by_event.setdefault(usage.eventId, {
                        "action": action,
                        "reasons": [],
                    })
                    if reason not in entry["reasons"]:
                        entry["reasons"].append(reason)

            result["scanned_draws"] = len(matches_by_event)
            logger.info("Searching %d draw calls (texture usage)..." %
                        result["scanned_draws"])
            t_start = time.time()

            for event_id in sorted(matches_by_event.keys()):
                entry = matches_by_event[event_id]
                action = entry["action"]
                result["matches"].append({
                    "event_id": action.eventId,
                    "name": action.GetName(structured_file),
                    "match_reason": "; ".join(entry["reasons"]),
                })

            logger.info("Search completed in %.2f seconds. Found %d matches out of %d draw calls." % (
                time.time() -
                t_start, len(result["matches"]), result["scanned_draws"]
            ))

        self._invoke(callback)
        result["total_matches"] = len(result["matches"])
        return result

    def find_draws_by_resource(self, resource_id):
        """Find all draw calls using a specific resource ID (exact match)."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        target_rid = Parsers.parse_resource_id(resource_id, self.ctx)

        result = {"matches": [], "scanned_draws": 0}

        def callback(controller):
            usage_events = controller.GetUsage(target_rid)
            structured_file = controller.GetStructuredFile()
            matches_by_event = {}

            logger.info("Found %d usage events for resource %s. Filtering draw calls..." %
                        (len(usage_events), target_rid))
            for usage in usage_events:
                if usage.eventId == 0:
                    continue

                action = self.ctx.GetAction(usage.eventId)
                if not action:
                    continue

                if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch)):
                    continue

                reason = self._format_resource_usage(usage, self.ctx)
                entry = matches_by_event.setdefault(usage.eventId, {
                    "action": action,
                    "reasons": [],
                })
                if reason not in entry["reasons"]:
                    entry["reasons"].append(reason)

            result["scanned_draws"] = len(matches_by_event)
            logger.info("Searching %d draw calls (resource usage)..." %
                        result["scanned_draws"])
            t_start = time.time()

            for event_id in sorted(matches_by_event.keys()):
                entry = matches_by_event[event_id]
                action = entry["action"]
                result["matches"].append({
                    "event_id": action.eventId,
                    "name": action.GetName(structured_file),
                    "match_reason": "; ".join(entry["reasons"]),
                })

            logger.info("Search completed in %.2f seconds. Found %d matches out of %d draw calls." % (
                time.time() -
                t_start, len(result["matches"]), result["scanned_draws"]
            ))

        self._invoke(callback)
        result["total_matches"] = len(result["matches"])
        return result
