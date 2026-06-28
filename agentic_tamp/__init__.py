"""Agentic TAMP: solve individual TAMP instances with a Claude agent.

This package feeds a Claude agent the *same* inputs a TAMPEST task-and-motion
planner receives for a single problem instance, and validates the agent's plan
with TAMPEST's own checker, enabling a head-to-head comparison against the
real solver. Unlike robocode, the agent solves one concrete instance rather
than a generalized policy over a distribution of problems.
"""
