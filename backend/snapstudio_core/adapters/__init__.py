"""Versioned adapters: provider payloads in, normalised foundation documents out.

An adapter never touches the network (the host layer fetches through
`foundation.netguard`); it only turns a payload it was handed into documents. See
`base.Adapter` and `registry`.
"""
