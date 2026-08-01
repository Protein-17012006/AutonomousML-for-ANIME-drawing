"""The active workspace: an in-progress run that survives a reload.

The four routes in `api.py` are not a design of ours. The deployed frontend
already calls them and gets 404, so their shapes were extracted field-by-field
from the JS the site serves — the source that calls them exists in no commit of
either repository. `models.py` records which client behaviour each field feeds.
"""
