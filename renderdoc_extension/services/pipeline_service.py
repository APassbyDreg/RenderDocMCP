"""
Pipeline state service for RenderDoc.
"""

import renderdoc as rd

from ..utils import Parsers, Serializers, logger


class PipelineService:
    """Pipeline state service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def get_shader_details(self, event_id, stage):
        """Get full shader information (source/disasm, CBs, SRVs, UAVs) for a specific stage."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"shader": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)
            pipe = controller.GetPipelineState()
            stage_enum = Parsers.parse_stage(stage)

            shader = pipe.GetShader(stage_enum)
            if shader == rd.ResourceId.Null():
                result["error"] = "No %s shader bound" % stage
                return

            reflection = pipe.GetShaderReflection(stage_enum)
            if not reflection:
                result["error"] = "No reflection available for %s shader" % stage
                return

            result["shader"] = Serializers.serialize_stage_shader_info(
                pipe, controller, stage_enum, stage, reflection, full=True, ctx=self.ctx
            )

        self._invoke(callback)

        if result["error"]:
            return result
        return result["shader"]

    def get_pipeline_state(self, event_id):
        """Get pipeline state (IA, viewport, output merger) at a specific event."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"pipeline": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            action = self.ctx.GetAction(event_id)
            is_drawcall = bool(
                action.flags & rd.ActionFlags.Drawcall) if action else False
            
            if not is_drawcall:
                result["error"] = "Event ID %d is not a draw call" % event_id
                return

            pipe = controller.GetPipelineState()
            api = controller.GetAPIProperties().pipelineType

            pipeline_info = {
                "event_id": event_id,
                "api": str(api),
                "is_drawcall": is_drawcall,
            }

            # Input assembly
            try:
                ia = pipe.GetIAState()
                if ia:
                    pipeline_info["input_assembly"] = {
                        "topology": str(ia.topology)}
            except Exception:
                pass

            # Viewport and scissor
            try:
                vp_scissor = pipe.GetViewportScissor()
                if vp_scissor:
                    pipeline_info["viewports"] = [
                        {
                            "x": v.x,
                            "y": v.y,
                            "width": v.width,
                            "height": v.height,
                            "min_depth": v.minDepth,
                            "max_depth": v.maxDepth,
                        }
                        for v in vp_scissor.viewports
                    ]
            except Exception:
                pass

            # Output merger (render targets + depth)
            try:
                om = pipe.GetOutputMerger()
                if om:
                    rts = [
                        {"index": i, "resource_id": str(rt.resourceId)}
                        for i, rt in enumerate(om.renderTargets)
                        if rt.resourceId != rd.ResourceId.Null()
                    ]
                    pipeline_info["render_targets"] = rts
                    if om.depthTarget.resourceId != rd.ResourceId.Null():
                        pipeline_info["depth_target"] = str(om.depthTarget.resourceId)
            except Exception:
                pass

            result["pipeline"] = pipeline_info

        self._invoke(callback)

        if result["error"]:
            return result
        return result["pipeline"]
