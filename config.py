import os

APP_NAME = "Pandoky"
APP_TAG = "A vibe-coded, Pandoc-based, Dokuwiki-inspired, flat-file, wiki-like CMS coded in Python"
FLASK_SECRET_KEY = os.environ.get('','shh')
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = 'data'
PAGES_DIR = os.path.join(DATA_DIR, 'pages')
BIB_DIR = os.path.join(DATA_DIR, 'bibliographies')
CSL_DIR = os.path.join(DATA_DIR, 'csl')
CACHE_DIR = os.path.join(APP_ROOT, 'cache') # For storing rendered HTML

# Page configuration
PAGE_EXTENSION = ".md"



# Media Files Configuration
MEDIA_DIR_NAME = 'media' # Subdirectory name within DATA_DIR
MEDIA_DIR = os.path.join(DATA_DIR, MEDIA_DIR_NAME)
ALLOWED_MEDIA_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'mp4', 'webm', 'ogg', 'pdf'}
MEDIA_URL_PREFIX = '/media' # How media files will be accessed via URL

# Slides
SLIDESHOW_DIR = os.path.join(APP_ROOT, 'cache', 'slideshows')

# Default Pandoc settings (can be overridden by page frontmatter if the J2MD template supports it)
DEFAULT_BIB = os.path.join(BIB_DIR,"references.yaml")
DEFAULT_CSL = os.path.join(CSL_DIR,"chicago-17.csl")
DEFAULT_PANDOC_MATH_RENDERER = '--mathjax=https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js' # e.g., 'mathjax', 'katex'
PANDOC_ARGS = [
    '--citeproc',
    '--shift-heading-level-by=1',
    #    DEFAULT_PANDOC_MATH_RENDERER,
    f'--bibliography={DEFAULT_BIB}',
    f'--csl={DEFAULT_CSL}'
]

# Email Configuration 
MAIL_SERVER = os.environ.get('MAIL_SERVER')
MAIL_PORT = os.environ.get('MAIL_PORT')
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS')
MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL')
MAIL_USERNAME = os.environ.get('MAIL_USERNAME') # Your email address
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') # Your email password or app-specific password
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Cyborg admin') 
MAIL_SUPPRESS_SEND = os.environ.get('MAIL_SUPPRESS_SEND', 'false').lower() in ['true', '1', 't'] # For testing without sending




