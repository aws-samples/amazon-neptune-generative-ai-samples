# MIT No Attribution
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# SPDX-License-Identifier: MIT-0

"""
neptune_guard.py - the guard: a Strands Agents hook that runs before every tool call.

You write before_tool in Cell 1.1 (this file is the reference answer). It asks three
functions in guard_rules.py:

    should_check(tool, args)              which calls commit AnyCompany to a supplier
    run_report(args)                      the validation report, or an exception
    block_message(supplier, ..., report)  the message that cancels the call, or None

and fails closed: if run_report raises, for any reason, the call is cancelled.
"""

import importlib

from strands.hooks import BeforeToolCallEvent
from strands.plugins import Plugin, hook


class NeptuneGuardPlugin(Plugin):
    """Validate every consequential action against the graph before it executes."""

    name = "neptune-guard"

    def __init__(self, rules=None):
        super().__init__()
        # The guard's three decisions, from guard_rules.py (or a module passed in).
        self.rules = rules or importlib.import_module("guard_rules")

    @hook
    def before_tool(self, event: BeforeToolCallEvent) -> None:
        tool = event.tool_use.get("name", "")
        args = event.tool_use.get("input") or {}
        if not self.rules.should_check(tool, args):
            return
        try:
            report = self.rules.run_report(args)
        except Exception as e:
            # Fail closed: an action that can't be proven valid doesn't happen.
            event.cancel_tool = (f"BLOCKED: could not validate this action against Neptune "
                                 f"({type(e).__name__}: {e}). No action was taken.")
            return
        message = self.rules.block_message(args.get("supplier_name"), args.get("product_name"),
                                           args.get("region_name"), report)
        if message:
            event.cancel_tool = message
