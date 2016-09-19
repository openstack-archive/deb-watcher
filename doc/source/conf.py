# -*- coding: utf-8 -*-
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from watcher import version as watcher_version

# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    'oslo_config.sphinxconfiggen',
    'oslosphinx',
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinxcontrib.httpdomain',
    'sphinxcontrib.pecanwsme.rest',
    'stevedore.sphinxext',
    'wsmeext.sphinxext',
    'watcher.doc',
]

wsme_protocols = ['restjson']
config_generator_config_file = '../../etc/watcher/watcher-config-generator.conf'
sample_config_basename = 'watcher'

# autodoc generation is a bit aggressive and a nuisance when doing heavy
# text edit cycles.
# execute "export SPHINX_DEBUG=1" in your terminal to disable

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'Watcher'
copyright = u'OpenStack Foundation'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
# The full version, including alpha/beta/rc tags.
release = watcher_version.version_info.release_string()
# The short X.Y version.
version = watcher_version.version_info.version_string()

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['watcher.']

exclude_patterns = [
    # The man directory includes some snippet files that are included
    # in other documents during the build but that should not be
    # included in the toctree themselves, so tell Sphinx to ignore
    # them when scanning for input files.
    'man/footer.rst',
    'man/general-options.rst',
]

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# -- Options for man page output --------------------------------------------

# Grouping the document tree for man pages.
# List of tuples 'sourcefile', 'target', u'title', u'Authors name', 'manual'

man_pages = [
    ('man/watcher-api', 'watcher-api', u'Watcher API Server',
     [u'OpenStack'], 1),
    ('man/watcher-applier', 'watcher-applier', u'Watcher Applier',
     [u'OpenStack'], 1),
    ('man/watcher-db-manage', 'watcher-db-manage',
     u'Watcher Db Management Utility', [u'OpenStack'], 1),
    ('man/watcher-decision-engine', 'watcher-decision-engine',
     u'Watcher Decision Engine', [u'OpenStack'], 1),
]

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
# html_theme_path = ["."]
# html_theme = '_theme'
# html_static_path = ['static']
html_theme_options = {'incubating': True}

# Output file base name for HTML help builder.
htmlhelp_basename = '%sdoc' % project

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    ('index',
     '%s.tex' % project,
     u'%s Documentation' % project,
     u'OpenStack Foundation', 'manual'),
]

# Example configuration for intersphinx: refer to the Python standard library.
# intersphinx_mapping = {'http://docs.python.org/': None}
