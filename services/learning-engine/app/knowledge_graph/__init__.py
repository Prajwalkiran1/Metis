"""Concept knowledge graph (M7e).

Starts as NetworkX in-memory persisted to R2; evolves to Neo4j when
scale demands it. The contract exposed to the rest of Metis is a single
``POST /concepts/related`` endpoint — implementation details stay here.
"""
