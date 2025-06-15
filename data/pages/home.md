---
date: June 14, 2025
title: What is Pandoky?
author: Ryan Schram
bibliography: "file"
---

# Pandoky: A vibe-coded, Pandoc-based, Dokuwiki-inspired, flat-file, wiki-like CMS coded in Python
 
![Figure 1. Current mood.](vibe.jpg "A Frinkiac.com screengrab from an episode of The Simpsons. Marge enters the living room to find Homer on the couch with a small blue bird pecking at the three hairs on his head. In the original episode, Homer replies to Marge, &ldquo;He's grooming me.&rdquo; In this altered image, the caption reads &ldquo;I vibe-coded it.&rdquo; Same, Homer. Same...")

Pandoky is a lightweight, flat-file based Content Management System (CMS) inspired by DokuWiki, built using Python, Flask, and Pandoc. It allows for easy creation and management of Markdown-based wiki pages with a focus on extensibility through a plugin architecture. All code was created in an interactive chat session with Google Gemini 2.5 pro (preview). The AI followed the instructions given by a human creator, starting with the prompt, 

>  I have a new vibe coding project for you. Dokuwiki is a content management system based on flat file data storage. It's implemented in PHP. I would like to create a dokuwiki clone implemented in python. It should have the same basic architecture as Dokuwiki including plug-in extensibility.[^chat] 

[^chat]: The full chat transcript is (for now) available here: <https://g.co/gemini/share/8e3b3be23d77>.

The AI replied with, initially, an overview of how one might create such an app, and then a skeleton for a Flask app, followed by initial versions of core files, basic templates and static assets,  and plug-ins. The human creator in turn followed the instructions of the AI, asked questions of procedure, copied the files, ran them, reported errors, made changes (or copied over corrected or improved versions of different components), and then suggested new plug-ins or expanded functions.[^pandoc] 

Who was the lord and who was the servant? Is the human a creator, worker, or just another Google customer? Is the AI a worker, a creator, or just another product? It is a question for the ages. 

Please use and test this (hopefully functional and relatively safe) app, find ways to improve it, and share your results. I won't necessarily be able to respond to issues but I look forward to seeing what others can do to improve or extend this initial effort. 

[^pandoc]: At some point, Pandoc was added as the core rendering engine because the human likes using Pandoc. He knows there's a performance cost by launching a new process on every render. 

## Key features

* **Flat-File Storage**: All content pages are stored as Markdown files with YAML frontmatter in the `data/pages/` directory. No database is required for core content.
* **Markdown with YAML Frontmatter**: Pages are composed in Markdown, with metadata (title, author, date, bibliography settings, etc.) managed in a YAML block at the top of each file.
* **Namespace Support**: Organize pages hierarchically using `/` in page names (e.g., `docs/setup/installation`). Directories are created automatically.
* **Pandoc Powered Rendering**: Leverages the power of Pandoc for:
    * Converting Markdown to HTML.
    * Processing citations (via `--citeproc`) using bibliography files (BibTeX, CSL JSON/YAML) and CSL styles.
    * Rendering mathematical notation (e.g., via MathJax[^math]).
* **Jinja2 Markdown Pre-processing**: Uses Jinja2 templates to pre-process Markdown content before it's sent to Pandoc, allowing dynamic content generation within Markdown files.
* **Plugin Architecture**: Designed for modularity, allowing new features to be added as self-contained plugins. Current plugins[^plug] include:
    * **User Authentication**: Secure user registration with email verification, login/logout, and password reset functionality.
    * **Simple ACL System**: Global permission management based on user groups ("anonymous", "authenticated", custom groups) and super admins.
    * **ACL Admin Editor**: Web interface for administrators to manage site configuration (admin users, default permissions), custom user groups, and permissions for these groups. Also includes an interface to manage user accounts (create/delete).
    * **Full-Text Indexer**: Creates and maintains an inverted index and TF-IDF vectors for page content, enabling search capabilities. Includes an admin trigger for full TF-IDF recalculation.
    * **Search Plugin**: Provides a search interface to query the full-text index.
    * **Similar Pages Plugin**: Introduces a `~~SIMILAR(N)~~` macro to display a list of N similar pages based on TF-IDF cosine similarity.
    * **Media Manager**: Admin interface to upload, list, and delete media files (images, videos, PDFs). Markdown syntax `![alt](filename.jpg)` is automatically resolved to serve these files.
    * **Bibliography Manager**: Admin interface to upload, list, and delete bibliography files (e.g., `.bib`, `.csljson`, `.yaml`).
* **Wikilinks**: Supports `[[Page Name]]`, `[[Namespace/Page Name]]`, and `[[Namespace:Page Name|Display Text]]` style wikilinks.
* **Static Asset Serving**: Correctly serves static files like `favicon.ico`.

[^plug]: tbh I think these plug-ins all depend on each other. They were created in the same chat and that usually initiated several changes to related files, and to `app.py`. This was really at the outer limits of my knowledge of software architecture. 

[^math]: The AI felt this was important to include and I let it have this one to avoid an argument. 

## Core technologies

* **Python 3**
* **Flask**: Micro web framework.
* **Pandoc**: Universal document converter.
* **Jinja2**: Templating engine.
* **pypandoc**: Python wrapper for Pandoc.
* **python-frontmatter**: Parses YAML frontmatter from Markdown files.
* **dateparser**: For flexible date string parsing in templates.
* **Werkzeug**: For password hashing and other web utilities.


## Setup and running (Development)

1.  **Prerequisites**:
    * Python 3.9+
    * Node.js and npm
    * Marp CLI
    * Pandoc executable installed and in your system's PATH.
2.  **Clone the repository** (if applicable).
3.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Linux/macOS
    # venv\Scripts\activate   # On Windows
    ```
4.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
5.  **Configuration**:
    * Review and adjust `config.py` if needed.
    * Set the following environment variables: 
        * `FLASK_SECRET_KEY`
    * For email functionality (account verification, password reset), set the following environment variables (or configure directly in `config.py` **for development only**):
        * `MAIL_SERVER`
        * `MAIL_PORT`
        * `MAIL_USE_TLS`
        * `MAIL_USERNAME`
        * `MAIL_PASSWORD`
        * `MAIL_DEFAULT_SENDER`
6.  **Initialize data files**:
    * On the first run, plugins should create their necessary JSON data files in the `data/` directory with default values.
    * Register an initial admin user via `/auth/register` and then ensure this username is added to the `"admin_users"` list in `data/acl_config.json`.
7.  **Run the development server**:
    ```bash
    python app.py
    ```
    The application will typically be available at `http://127.0.0.1:5000/`.

## Basic usage

* **View pages**: Navigate to `/<page_name>` or `/<namespace>/<page_name>`.
* **Create/edit pages**: Use wikilinks to non-existent pages or the "Edit Page" button.
* **Admin interfaces**: Access admin sections via `/admin/acl` (for ACLs) and `/admin/media` (for media), `/admin/bibliography` (for bib files) after logging in as an admin user.

## Future plans

I plan on testing this version of the app online and then possibly trying to create (with AI assistance) plugins that emulate functions I use with Dokuwiki, for instance a deck.js plugin, k-means clustering, and a page inclusion plugin. A fun idea would be to learn how to use Javascript `fetch()` to interact with Flask endpoints, opening the possibility of perpetual scrolling, but then, who wants to contribute to the gradual brainrot of the terminally online? 


---
**AI acknowledgement:** This README was itself written by Google Gemini 2.5 Pro (preview) at the end of the development process. The introduction was expanded and the document was edited by the human creator. 
