"""Mock backend services: order API, returns system, KB search, ticketing stub.

These wrap the JSON fixtures with the same shape a real integration would expose,
so the agent and eval harness exercise realistic tool calls without live systems.
"""
