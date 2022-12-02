import random
random.seed(0)
import numpy as np
np.random.seed(0)
import tensorflow as tf
import onnx_graphsurgeon as gs
from onnx2tf.utils.common_functions import (
    get_replacement_parameter,
    replace_parameter,
    get_constant_or_variable,
    print_node_info,
    inverted_operation_enable_disable,
    make_tf_node_info,
    explicit_broadcast,
    pre_process_transpose,
    post_process_transpose,
    disable_unnecessary_transpose,
)


@print_node_info
@inverted_operation_enable_disable
@get_replacement_parameter
def make_node(
    *,
    graph_node: gs.Node,
    tf_layers_dict: dict,
    **kwargs: dict,
):
    """Mul

    Parameters
    ----------
    graph_node: gs.Node
        graph_surgeon Node

    tf_layers_dict: dict
        optype, shape, dtype, tensorflow graph
    """
    before_op_output_shape_trans_1 = \
        tf_layers_dict.get(graph_node.inputs[0].name, {}).get('before_op_output_shape_trans', True)
    before_op_output_shape_trans_2 = \
        tf_layers_dict.get(graph_node.inputs[1].name, {}).get('before_op_output_shape_trans', True)
    before_op_output_shape_trans = \
        before_op_output_shape_trans_1 \
        and before_op_output_shape_trans_2

    graph_node_input_1 = get_constant_or_variable(
        graph_node.inputs[0],
        before_op_output_shape_trans,
    )
    graph_node_input_2 = get_constant_or_variable(
        graph_node.inputs[1],
        before_op_output_shape_trans,
    )
    graph_node_output: gs.Variable = graph_node.outputs[0]
    shape = graph_node_output.shape
    dtype = graph_node_output.dtype

    # Preserving Graph Structure (Dict)
    tf_layers_dict[graph_node_output.name] = {
        'optype': graph_node.op,
        'shape': shape,
        'dtype': dtype,
    }

    input_tensor_1 = tf_layers_dict[graph_node_input_1.name]['tf_node'] \
        if isinstance(graph_node_input_1, gs.Variable) else graph_node_input_1
    input_tensor_2 = tf_layers_dict[graph_node_input_2.name]['tf_node'] \
        if isinstance(graph_node_input_2, gs.Variable) else graph_node_input_2

    # Disable unnecessary Transpose
    #   1. If both x and y are gs.Variable
    #   2. If only one of the two is the output of Transpose
    #   3. If the perm of the Transpose is [0,2,1] or [0,3,1,2] or [0,4,1,2,3]
    #   4. Furthermore, if the shape of x and y are mismatched
    graph_node_input_1, graph_node_input_2, input_tensor_1, input_tensor_2 = \
        disable_unnecessary_transpose(
            graph_node_input_1=graph_node_input_1,
            graph_node_input_2=graph_node_input_2,
            input_tensor_1=input_tensor_1,
            input_tensor_2=input_tensor_2,
        )

    input_tensor_1, input_tensor_2 = explicit_broadcast(
        const_or_var_1=input_tensor_1,
        const_or_var_2=input_tensor_2,
        graph_node=graph_node,
        tf_layers_dict= tf_layers_dict,
    )

    # Shape Unmatched Special Avoidance Workaround
    # At least one True value for same_input_shape_as_onnx
    # At least one True value in nhwc_flags
    # same_input_shape_as_onnx == True and nhwc_flags == False and 3D or 4D or 5D tensor is NHWC transposed
    nhwc_flag_1 = False
    same_input_shape_as_onnx_1 = False
    if isinstance(input_tensor_1, gs.Variable):
        nhwc_flag_1 =tf_layers_dict[input_tensor_1.name]['nhwc'] \
            if 'nhwc' in tf_layers_dict[input_tensor_1.name].keys() else False
        same_input_shape_as_onnx_1 = True if len(graph_node_input_1.shape) > 0 \
            and graph_node_input_1.shape == tf_layers_dict[input_tensor_1.name]['tf_node'].shape else False
    else:
        nhwc_flag_1 = False
        same_input_shape_as_onnx_1 = True if len(graph_node_input_1.shape) > 0 \
            and graph_node_input_1.shape == input_tensor_1.shape else False
    nhwc_flag_2 = False
    same_input_shape_as_onnx_2 = False
    if isinstance(input_tensor_2, gs.Variable):
        nhwc_flag_2 =tf_layers_dict[input_tensor_2.name]['nhwc'] \
            if 'nhwc' in tf_layers_dict[input_tensor_2.name].keys() else False
        same_input_shape_as_onnx_2 = True if len(graph_node_input_2.shape) > 0 \
            and graph_node_input_2.shape == tf_layers_dict[input_tensor_2.name]['tf_node'].shape else False
    else:
        nhwc_flag_2 = False
        same_input_shape_as_onnx_2 = True if len(graph_node_input_2.shape) > 0 \
            and graph_node_input_2.shape == input_tensor_2.shape else False

    same_input_shape_as_onnxs = [same_input_shape_as_onnx_1, same_input_shape_as_onnx_2]
    nhwc_flags = [nhwc_flag_1, nhwc_flag_2]
    if True in same_input_shape_as_onnxs and True in nhwc_flags:
        values = [input_tensor_1, input_tensor_2]
        for idx, (same_input_shape_as_onnx, nhwc_flag) in enumerate(zip(same_input_shape_as_onnxs, nhwc_flags)):
            if same_input_shape_as_onnx and not nhwc_flag:
                if len(values[idx].shape) == 3:
                    values[idx] = tf.transpose(a=values[idx], perm=[0,2,1])
                elif len(values[idx].shape) == 4:
                    values[idx] = tf.transpose(a=values[idx], perm=[0,2,3,1])
                elif len(values[idx].shape) == 5:
                    values[idx] = tf.transpose(a=values[idx], perm=[0,2,3,4,1])

    # Param replacement
    input_tensor_1 = replace_parameter(
        value_before_replacement=input_tensor_1,
        param_target='inputs',
        param_name=graph_node.inputs[0].name,
        **kwargs,
    )
    input_tensor_2 = replace_parameter(
        value_before_replacement=input_tensor_2,
        param_target='inputs',
        param_name=graph_node.inputs[1].name,
        **kwargs,
    )

    # Pre-process transpose
    input_tensor_1 = pre_process_transpose(
        value_before_transpose=input_tensor_1,
        param_target='inputs',
        param_name=graph_node.inputs[0].name,
        **kwargs,
    )
    input_tensor_2 = pre_process_transpose(
        value_before_transpose=input_tensor_2,
        param_target='inputs',
        param_name=graph_node.inputs[1].name,
        **kwargs,
    )

    # Generation of TF OP
    tf_layers_dict[graph_node_output.name]['tf_node'] = \
        tf.math.multiply(
            x=input_tensor_1,
            y=input_tensor_2,
            name=graph_node.name,
        )

    # Post-process transpose
    tf_layers_dict[graph_node_output.name]['tf_node'] = post_process_transpose(
        value_before_transpose=tf_layers_dict[graph_node_output.name]['tf_node'],
        param_target='outputs',
        param_name=graph_node.outputs[0].name,
        **kwargs,
    )

    # Generation of Debug Info
    tf_layers_dict[graph_node_output.name]['tf_node_info'] = \
        make_tf_node_info(
            node_info={
                'tf_op_type': tf.math.multiply,
                'tf_inputs': {
                    'x': input_tensor_1,
                    'y': input_tensor_2,
                },
                'tf_outputs': {
                    'output': tf_layers_dict[graph_node_output.name]['tf_node'],
                },
            }
        )
