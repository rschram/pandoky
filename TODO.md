# TO DO

## Roadmap for future work, reordered to prioritize foundational improvements.

*I asked the AI to play the role of teacher, and it's really committing to the bit. I have homework.*

### Phase 1: Solidify the Foundation (Core Architecture & Stability)

*These tasks make the application robust, maintainable, and fix fundamental issues. They should be completed before major new features are added.*

1.  ~~Refactoring the `view_page` function for clarity and maintainability.~~
    * [X] **Subtask 1:** Create new helper function stubs: `_get_page_data`, `_process_markdown_content`, and `_render_page_html`.
    * [X] **Subtask 2:** Isolate data retrieval logic into `_get_page_data`.
    * [X] **Subtask 3:** Isolate Markdown hook processing into `_process_markdown_content`.
    * [X] **Subtask 4:** Isolate Pandoc HTML conversion and its error handling into `_render_page_html`.
    * [X] **Subtask 5:** Rewrite `view_page` to be a lean "controller" that orchestrates the calls to the new helper functions.

2.  **Implement Advisory File Locking to prevent edit conflicts.**
    * [ ] Design a system to create a `.lock` file when a user begins editing a page.
    * [ ] Before rendering the edit page, check for a lock file and show a "page is locked" message if it exists.
    * [ ] Ensure the lock file is deleted when a page is saved or when the user cancels the edit.

3.  **Redirecting a user to the last page seen after login.**
    * [ ] Review all redirects to the login page and ensure the `next=request.url` parameter is passed.
    * [ ] Strengthen the login route to securely handle and validate the `next` parameter.

---

### Phase 2: Enhance Core Content Capabilities

*With a stable core, we can now add powerful features for content authors.*

4.  **Recording and displaying page history.**
    * [ ] Choose a versioning strategy (e.g., diff files or a Git-based approach).
    * [ ] Create a plugin that hooks into `after_page_save` to record the change, user, and timestamp.
    * [ ] Create a new route and template to display the history for a given page.

5.  **Transclusion of text from other pages.**
    * [ ] Extend the `process_page_macros` hook to recognize an `~~INCLUDE:page-name~~` macro.
    * [ ] Implement the logic to recursively fetch and insert the content from the target page.
    * [ ] Add protection against infinite loops (e.g., Page A includes Page B, which includes Page A).

---

### Phase 3: Introduce Interactivity & Modern UX

*These features focus on the reader's experience, adding modern, interactive elements.*

6.  **Interactivity for readers via Javascript (voting/rating).**
    * [ ] Create a new plugin with a Flask API endpoint (e.g., `POST /api/rate/<page_name>`) to receive and store votes.
    * [ ] Add JavaScript to the page templates that uses `fetch()` to call this API.
    * [ ] Use JavaScript to dynamically update the rating display on the page without a full reload.

7.  **Touch event navigation (swipe to edit/random).**
    * [ ] Add JavaScript listeners for `touchstart`, `touchmove`, and `touchend` events.
    * [ ] Implement logic to detect a horizontal swipe and trigger a page navigation (`window.location.href`).

8.  **Perpetual scroll based on page similarity.**
    * [ ] Create a new API endpoint that returns the rendered HTML of the most similar page.
    * [ ] Use the JavaScript `Intersection Observer` API to detect when a user scrolls to the bottom of a page.
    * [ ] Trigger a `fetch()` call to the API and dynamically append the returned HTML to the page.

---

### Future phases that the AI "forgot" about while it was handing out assignments

* Refactoring plugin architecture to check for plugin dependencies and add required plugins data to 
each existing plugin file. 
* Implementing a macro plugin that lists clusters of related pages using 
K-means clustering.


**AI acknowledgement:** The AI is giving me more instructions on what to do next.
