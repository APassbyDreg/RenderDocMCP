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

            pipeline_info = {}

            # Input assembly
            try:
                topology = pipe.GetPrimitiveTopology()
                pipeline_info["input_assembly"] = {
                    "topology": str(topology),
                }
                # Index buffer
                ibuf = pipe.GetIBuffer()
                if ibuf.resourceId != rd.ResourceId.Null():
                    pipeline_info["input_assembly"]["index_buffer"] = {
                        "resource_id": str(ibuf.resourceId),
                        "byte_offset": ibuf.byteOffset,
                        "byte_stride": ibuf.byteStride,
                    }
                # Vertex buffers
                vbufs = pipe.GetVBuffers()
                if vbufs:
                    pipeline_info["input_assembly"]["vertex_buffers"] = [
                        {
                            "resource_id": str(vb.resourceId),
                            "byte_offset": vb.byteOffset,
                            "byte_stride": vb.byteStride,
                        }
                        for vb in vbufs
                        if vb.resourceId != rd.ResourceId.Null()
                    ]
            except Exception as e:
                logger.error(
                    "Failed to get input assembly state for event %d: %s", event_id, e)

            # Viewports and scissors
            try:
                viewports = []
                for i in range(16):
                    vp = pipe.GetViewport(i)
                    if not vp.enabled or (vp.width == 0 and vp.height == 0):
                        break
                    viewports.append({
                        "x": vp.x,
                        "y": vp.y,
                        "width": vp.width,
                        "height": vp.height,
                        "min_depth": vp.minDepth,
                        "max_depth": vp.maxDepth,
                    })
                if viewports:
                    pipeline_info["viewports"] = viewports
                scissors = []
                for i in range(16):
                    sc = pipe.GetScissor(i)
                    if not sc.enabled or (sc.width == 0 and sc.height == 0):
                        break
                    scissors.append({
                        "x": sc.x,
                        "y": sc.y,
                        "width": sc.width,
                        "height": sc.height,
                    })
                if scissors:
                    pipeline_info["scissors"] = scissors
            except Exception as e:
                logger.error(
                    "Failed to get viewport/scissor state for event %d: %s", event_id, e)

            # Output targets (render targets + depth)
            try:
                output_targets = pipe.GetOutputTargets()
                rts = [
                    {"resource_id": str(rt.resource)}
                    for rt in output_targets
                    if rt.resource != rd.ResourceId.Null()
                ]
                pipeline_info["render_targets"] = rts

                depth = pipe.GetDepthTarget()
                if depth.resource != rd.ResourceId.Null():
                    pipeline_info["depth_target"] = str(depth.resource)
            except Exception as e:
                logger.error(
                    "Failed to get output targets for event %d: %s", event_id, e)

            result["pipeline"] = pipeline_info

        self._invoke(callback)

        if result["error"]:
            return result
        return result["pipeline"]
