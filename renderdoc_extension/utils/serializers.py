"""
Serialization utility functions for RenderDoc data types.
"""

from . import logger

import renderdoc as rd


def shader_var_to_value(var):
    # recursive for (struct / array)
    if len(var.members) > 0:
        # array
        if var.members[0].name.startswith('['):
            return [shader_var_to_value(m) for m in var.members]
        # struct
        return {m.name: shader_var_to_value(m) for m in var.members}

    t = var.type
    rows, cols = var.rows, var.columns
    total = rows * cols

    if t in (rd.VarType.Float, rd.VarType.Half):
        raw = [var.value.f32v[i] for i in range(total)]
    elif t == rd.VarType.Double:
        raw = [var.value.f64v[i] for i in range(total)]
    elif t in (rd.VarType.SInt, rd.VarType.SShort, rd.VarType.SByte):
        raw = [var.value.s32v[i] for i in range(total)]
    elif t in (rd.VarType.UInt, rd.VarType.UShort, rd.VarType.UByte,
               rd.VarType.Bool, rd.VarType.Enum):
        raw = [var.value.u32v[i] for i in range(total)]
    elif t == rd.VarType.SLong:
        raw = [var.value.s64v[i] for i in range(total)]
    elif t == rd.VarType.ULong:
        raw = [var.value.u64v[i] for i in range(total)]
    else:
        return None  # skip special types like GPUPointer

    # bool
    if t == rd.VarType.Bool:
        raw = [bool(v) for v in raw]

    # scaler
    if total == 1:
        return raw[0]
    # vector
    if rows == 1:
        return raw
    # matrix
    return [raw[r * cols:(r + 1) * cols] for r in range(rows)]


def cbuffer_vars_to_dict(shader_vars):
    """List[ShaderVariable] → dict"""
    return {v.name: {"value": shader_var_to_value(v), "type": str(v.type.name)} for v in shader_vars}


class Serializers:
    """Serialization utility functions (static methods)"""

    @staticmethod
    def serialize_flags(flags):
        """Convert ActionFlags to list of strings"""
        flag_names = []
        flag_map = [
            (rd.ActionFlags.Drawcall, "Drawcall"),
            (rd.ActionFlags.Dispatch, "Dispatch"),
            (rd.ActionFlags.Clear, "Clear"),
            (rd.ActionFlags.PushMarker, "PushMarker"),
            (rd.ActionFlags.PopMarker, "PopMarker"),
            (rd.ActionFlags.SetMarker, "SetMarker"),
            (rd.ActionFlags.Present, "Present"),
            (rd.ActionFlags.Copy, "Copy"),
            (rd.ActionFlags.Resolve, "Resolve"),
            (rd.ActionFlags.GenMips, "GenMips"),
            (rd.ActionFlags.PassBoundary, "PassBoundary"),
            (rd.ActionFlags.Indexed, "Indexed"),
            (rd.ActionFlags.Instanced, "Instanced"),
            (rd.ActionFlags.Auto, "Auto"),
            (rd.ActionFlags.Indirect, "Indirect"),
            (rd.ActionFlags.ClearColor, "ClearColor"),
            (rd.ActionFlags.ClearDepthStencil, "ClearDepthStencil"),
            (rd.ActionFlags.BeginPass, "BeginPass"),
            (rd.ActionFlags.EndPass, "EndPass"),
        ]
        for flag, name in flag_map:
            if flags & flag:
                flag_names.append(name)
        return flag_names

    @staticmethod
    def serialize_variables(variables):
        """Serialize shader variables to JSON format"""
        result = []
        for var in variables:
            var_info = {
                "name": var.name,
                "type": str(var.type.name),
                "rows": var.rows,
                "columns": var.columns,
            }

            # Get value based on type
            try:
                if var.type == rd.VarType.Float:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.f32v[:count])
                elif var.type == rd.VarType.Int:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.s32v[:count])
                elif var.type == rd.VarType.UInt:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.u32v[:count])
            except Exception:
                pass

            # Nested members
            if var.members:
                var_info["members"] = Serializers.serialize_variables(var.members)

            result.append(var_info)

        return result

    @staticmethod
    def serialize_actions(
        actions,
        structured_file,
        include_children,
        marker_filter=None,
        exclude_markers=None,
        event_id_min=None,
        event_id_max=None,
        only_actions=False,
        only_markers=False,
        flags_filter=None,
        _in_matching_marker=False,
    ):
        """
        Serialize action list to JSON-compatible format with filtering.

        Args:
            actions: List of actions to serialize
            structured_file: Structured file for action names
            include_children: Include child actions in hierarchy
            marker_filter: Only include actions under markers containing this string
            exclude_markers: Exclude actions under markers containing these strings
            event_id_min: Only include actions with event_id >= this value
            event_id_max: Only include actions with event_id <= this value
            only_actions: Exclude marker actions (PushMarker/PopMarker/SetMarker)
            only_markers: Only include marker actions (PushMarker/PopMarker/SetMarker)
            flags_filter: Only include actions with these flags
            _in_matching_marker: Internal flag for marker_filter recursion
        """
        serialized = []

        # Build flags filter set for efficient lookup
        flags_filter_set = None
        if flags_filter:
            flags_filter_set = set(flags_filter)

        def is_subsequence_ignore_case(needle, haystack):
            if not needle:
                return True
            needle = needle.casefold()
            haystack = haystack.casefold()
            it = iter(haystack)
            for ch in needle:
                if ch.isspace():
                    continue
                if ch not in it:
                    return False
            return True

        for action in actions:
            name = action.GetName(structured_file)
            flags = action.flags

            # Check if this is a marker
            is_push_marker = flags & rd.ActionFlags.PushMarker
            is_set_marker = flags & rd.ActionFlags.SetMarker
            is_pop_marker = flags & rd.ActionFlags.PopMarker
            is_marker = is_push_marker or is_set_marker or is_pop_marker

            # 1. exclude_markers check - skip this marker and all its children
            if exclude_markers and is_marker:
                if any(ex in name for ex in exclude_markers):
                    continue

            # 2. marker_filter check - track if we're inside a matching marker
            in_matching = _in_matching_marker
            if marker_filter:
                if (is_push_marker or is_set_marker) and is_subsequence_ignore_case(marker_filter, name):
                    in_matching = True

            # 3. Determine if action passes event_id range filter
            # For markers with children, we check children even if marker is outside range
            in_range = True
            if not is_marker:
                if event_id_min is not None and action.eventId < event_id_min:
                    in_range = False
                if event_id_max is not None and action.eventId > event_id_max:
                    in_range = False

            # 4. only_markers check - skip non-markers but process their children
            if only_markers and not is_marker:
                if include_children and action.children:
                    child_actions = Serializers.serialize_actions(
                        action.children,
                        structured_file,
                        include_children,
                        marker_filter=marker_filter,
                        exclude_markers=exclude_markers,
                        event_id_min=event_id_min,
                        event_id_max=event_id_max,
                        only_actions=only_actions,
                        only_markers=only_markers,
                        flags_filter=flags_filter,
                        _in_matching_marker=in_matching,
                    )
                    serialized.extend(child_actions)
                continue

            # 5. only_actions check - skip markers but process their children
            if only_actions and not only_markers and is_marker:
                if include_children and action.children:
                    child_actions = Serializers.serialize_actions(
                        action.children,
                        structured_file,
                        include_children,
                        marker_filter=marker_filter,
                        exclude_markers=exclude_markers,
                        event_id_min=event_id_min,
                        event_id_max=event_id_max,
                        only_actions=only_actions,
                        only_markers=only_markers,
                        flags_filter=flags_filter,
                        _in_matching_marker=in_matching,
                    )
                    serialized.extend(child_actions)
                continue

            # 6. flags_filter check - only for non-markers
            if flags_filter_set and not is_marker:
                flag_names = Serializers.serialize_flags(flags)
                if not any(f in flags_filter_set for f in flag_names):
                    continue

            # 7. Check if this action should be included based on marker_filter
            passes_marker_filter = not marker_filter or in_matching

            # 8. For markers with children, check if any children pass filters
            children_result = []
            has_passing_children = False
            if include_children and action.children:
                children_result = Serializers.serialize_actions(
                    action.children,
                    structured_file,
                    include_children,
                    marker_filter=marker_filter,
                    exclude_markers=exclude_markers,
                    event_id_min=event_id_min,
                    event_id_max=event_id_max,
                    only_actions=only_actions,
                    only_markers=only_markers,
                    flags_filter=flags_filter,
                    _in_matching_marker=in_matching,
                )
                has_passing_children = len(children_result) > 0

            # Include the action if:
            # - It passes all filters (for leaf actions)
            # - It's a marker with children that pass filters (to maintain hierarchy)
            should_include = False
            if is_marker:
                # Include marker if it has children that pass filters
                should_include = has_passing_children or passes_marker_filter
            else:
                # Include leaf action if it passes all filters
                should_include = in_range and passes_marker_filter

            if should_include and not is_pop_marker:
                item = {
                    "event_id": action.eventId,
                    "action_id": action.actionId,
                    "name": name,
                }
                if not only_markers:
                    item["flags"] = Serializers.serialize_flags(flags)
                is_draw = flags & rd.ActionFlags.Drawcall
                is_dispatch = flags & rd.ActionFlags.Dispatch
                if is_draw:
                    item["num_indices"] = action.numIndices
                    item["num_instances"] = action.numInstances
                if is_dispatch:
                    item["dispatch_dimension"] = action.dispatchDimension
                if children_result:
                    item["children"] = children_result
                serialized.append(item)

        return serialized

    @staticmethod
    def serialize_descriptor(used, refl, full=False):
        """
        Serialize descriptor binding information to JSON-compatible format.
        
        Args:
            used: UsedDescriptor object
            refl: Shader reflection object
            full: Whether to include full details or just basic info
        """
        acc = used.access
        desc = used.descriptor
        cat = rd.CategoryForDescriptorType(acc.type)

        bind_name = ""
        if refl is not None and acc.index != rd.DescriptorAccess.NoShaderBinding:
            if cat == rd.DescriptorCategory.ReadOnlyResource:
                if acc.index < len(refl.readOnlyResources):
                    bind_name = refl.readOnlyResources[acc.index].name
            elif cat == rd.DescriptorCategory.ReadWriteResource:
                if acc.index < len(refl.readWriteResources):
                    bind_name = refl.readWriteResources[acc.index].name

        is_texture = acc.type == rd.DescriptorType.Image or acc.type == rd.DescriptorType.ReadWriteImage
        is_buffer = acc.type == rd.DescriptorType.Buffer or acc.type == rd.DescriptorType.ReadWriteBuffer
        is_typed_buffer = acc.type == rd.DescriptorType.TypedBuffer or acc.type == rd.DescriptorType.ReadWriteTypedBuffer

        data = {
            "shader_name":      bind_name,
            "descriptor_type":  str(acc.type),
            "resource":        str(desc.resource),
        }

        # return only simplified info if full details not requested
        if not full:
            return data

        data["shader_index"] = acc.index

        if is_texture:
            data.update({
                "first_mip":        desc.firstMip,
                "num_mips":         desc.numMips,
                "first_slice":      desc.firstSlice,
                "num_slices":       desc.numSlices,
                "texture_type":     str(desc.textureType),
            })
        if is_buffer or is_typed_buffer:
            data.update({
                "byte_offset":      desc.byteOffset,
                "byte_size":        desc.byteSize,
                "element_byte_size": desc.elementByteSize,
            })
        if is_typed_buffer or is_texture:
            data["format"] = str(
                desc.format.Name()) if desc.resource != rd.ResourceId.Null() else ""
        return data

    @staticmethod
    def serialize_const_block(pipe, stage, refl, controller, cb_index, cb, full=False):
        """
        Serialize constant buffer contents to JSON-compatible format
        
        Args:
            pipeline: Pipeline object
            stage: Shader stage
            controller: ReplayController object
            cb_index: Index of the constant buffer
            block: ConstantBufferData object containing buffer contents and variable info
            full: Whether to include full details or just basic info
        """
        result = {
            "name": cb.name,
            "byte_size": cb.byteSize,
            "buffer_backed": cb.bufferBacked,
        }
        if not cb.bufferBacked or not full:
            return result

        entry = pipe.GetShaderEntryPoint(stage)
        shader_id = refl.resourceId
        buf_id = cb.descriptor.resource

        shader_vars = controller.GetCBufferVariableContents(
            pipe.GetGraphicsPipelineObject(),       # pipeline object
            shader_id,  # shader resource id
            stage,      # shader stage
            entry,      # entry point name
            cb_index,   # constantBlocks index
            buf_id,     # GPU buffer id
            0,          # byte offset
            0,          # length（0 = read all）
        )

        cb_dict = cbuffer_vars_to_dict(shader_vars)
        result["data"] = cb_dict
        return result
