"""Crawling: turning an approved source into a queue of URLs, and draining it.

Everything here sits *around* the frozen fetch subsystem and calls into it. Nothing here reaches
inside it.
"""
