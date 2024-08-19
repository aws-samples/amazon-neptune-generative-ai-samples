"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

from st_cytoscape import cytoscape


def get_color(label):
    match label:
        case "Vulnerability":
            return "red"
        case "Component":
            return "yellow"
        case _:
            return "grey"


def get_id(label, n):
    match label:
        case "Vulnerability":
            return f"Vulnerability: {n['~properties']['id']}"
        case "Component":
            return n["~id"]
        case _:
            return "grey"


def setup_graph(data, key):
    elements = []

    for n in data["nodes"]:
        color = get_color(n["~labels"][0])
        id = get_id(n["~labels"][0], n)
        elements.append(
            {
                "data": {
                    "id": n["~id"],
                    "label": id,
                    "color": color,
                }
            }
        )

    for n in data["edges"]:
        elements.append(
            {"data": {"source": n["~start"], "target": n["~end"], "label": n["~type"]}}
        )
    stylesheet = [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "width": 20,
                "height": 20,
                "background-color": "data(color)",
            },
        },
        {
            "selector": "edge",
            "style": {
                "label": "data(label)",
                "width": 3,
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
            },
        },
    ]
    layout = {
        "name": "fcose",
        "animationDuration": 0,
        "padding": 50,
        "nodeDimensionsIncludeLabels": True,
        "nodeRepulsion": 4096,
        "fit": True,
    }
    return cytoscape(
        elements,
        stylesheet,
        layout=layout,
        selection_type="single",
        height="400px",
        key=key,
    )
