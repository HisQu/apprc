"""Central config for Paths (and Traversables)"""

# %%
# --- Standard Lib ---------------------
from pathlib import Path

# --- Deps -----------------------------
try:
    from holylog import LOG
except ImportError:
    import logging

    LOG = logging.getLogger(__name__)

# --- Local ----------------------------
from apprc import utils as ut



"""Syntax:
D_<NAME>     # Directory
<NAME>_x     # Filepath (Always include file extension!)
<NAME>_TXT   # Filepath of txt-format
<NAME>_JSON  # Filepath of json-format
"""

# =====================================================================
# == Resources for Site-Package
# =====================================================================
# !! Read-only! ---

# ---------------------------------------------------------------
# -- Package Root 
import apprc

ROOT_PKG: Path = ut.package_root_dir(apprc)
LOG.debug(f"📂 Opa-Rag package directory: '{ROOT_PKG}'")

# ---------------------------------------------------------------
# -- Paths to Resources
# D_PROMPTS = ROOT_PKG / "prompt"
# TEMPLATES_YAML = D_PROMPTS / "templates.yaml"




# %%
# raise SystemExit()

# =====================================================================
# == User Storage (Read and Write)
# =====================================================================
# > Stuff the program reads & writes somewhere on the filesystem outside of the package

# ---------------------------------------------------------------
# -- Storage Root from env variable

ROOT_STORAGE = ut.get_local_dir_from_env(
    env_var="apprc_STORAGE",
    env_file=".env.template",
)

# ---------------------------------------------------------------
# -- Top Level Dirs

# D_CORPUS = ROOT_STORAGE / "rag_corpus"
# D_WORKDIR = ROOT_STORAGE / "rag_workdir"
# D_RETRIEVED = ROOT_STORAGE / "rag_retrieved"

# ---------------------------------------------------------------
# -- Sub Dirs and Files

# D_TEXTS = D_CORPUS / "texts"
# ABREV_TSV = D_TEXTS / "raw" / "abkürzungen.tsv"
# ABREV_JSON = D_TEXTS / "abkürzungen.json"
# ABREV_TXT = D_TEXTS / "abkürzungen.txt"

# D_ONTO = D_CORPUS / "ontology"
# ONTO_OWL = D_ONTO / "raw" / "urn_webprotege_ontology.owl"
# # ONTO_OWL = D_ONTO / "raw" / "urn_webprotege_ontology-251208.owl"
# ENT_JSON = D_ONTO / "from_owl-entities.json"
# REL_JSON = D_ONTO / "from_owl-relationships.json"

# ---------------------------------------------------------------
# -- Output files

# SUBSET_OWL = D_RETRIEVED / "from_lightrag_subset.owl"
