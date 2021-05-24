from typing import Any
from typing import Callable
from typing import Optional

import torch

from nncf.torch.dynamic_graph.graph_tracer import GraphTracer
from nncf.torch.graph.graph import PTNNCFGraph
from nncf.torch.graph.graph import PTNNCFEdge
from nncf.torch.graph.graph import PTNNCFNode


class GraphBuilder:
    def __init__(self, custom_forward_fn: Callable[[torch.nn.Module], Any]):
        self.custom_forward_fn = custom_forward_fn

    def build_graph(self, model: torch.nn.Module, context_to_use: Optional['TracingContext'] = None,
                    as_eval: bool = False) -> PTNNCFGraph:
        tracer = GraphTracer(self.custom_forward_fn)
        traced_graph = tracer.trace_graph(model, context_to_use, as_eval)

        nncf_graph = PTNNCFGraph()
        for dynamic_graph_node in traced_graph.get_all_nodes():
            nncf_node = PTNNCFNode(
                node_id=dynamic_graph_node.node_id,
                ia_op_exec_context=dynamic_graph_node.op_exec_context.input_agnostic,
                data={
                    PTNNCFGraph.MODULE_ATTRIBUTES: dynamic_graph_node.module_attributes
                }
            )
            nncf_graph.add_nncf_node(nncf_node)

        for dynamic_graph_edge in traced_graph.get_all_edges():
            nncf_edge = PTNNCFEdge(
                from_node_id=dynamic_graph_edge.from_node_id,
                to_node_id=dynamic_graph_edge.to_node_id,
                data={
                    PTNNCFGraph.ACTIVATION_SHAPE_EDGE_ATTR: dynamic_graph_edge.activation_shape,
                    PTNNCFGraph.ACTIVATION_DTYPE_EDGE_ATTR: dynamic_graph_edge.activation_dtype,
                    PTNNCFGraph.IN_PORT_NAME_EDGE_ATTR: dynamic_graph_edge.input_port_id
                }
            )
            nncf_graph.add_edge(nncf_edge)
        return nncf_graph
