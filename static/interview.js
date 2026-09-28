const categories = [
  "experience",
  "project",
  "achievement",
  "skill",
  "education",
  "preference",
];
const $ = (selector) => document.querySelector(selector);

export function setupExperience({ api, action, notify, esc }) {
  let interview,
    background = [],
    confirmed = new Set(),
    busy = false,
    loadVersion = 0;

  function options(selected) {
    return categories
      .map(
        (category) =>
          `<option value="${category}" ${selected === category ? "selected" : ""}>${category[0].toUpperCase() + category.slice(1)}</option>`,
      )
      .join("");
  }

  function renderBackground() {
    $("#background-items").innerHTML = background.length
      ? background
          .map(
            (item, i) => `
      <article class="background-card" data-background="${esc(item.id)}">
        <div class="fact-heading"><span class="tag">${confirmed.has(item.id) ? "Saved in profile" : "Draft · save profile to confirm"}</span><button type="button" class="text-button" data-remove="${esc(item.id)}" aria-label="Remove experience detail ${i + 1}">Remove</button></div>
        <label>Detail ${i + 1} category<select data-field="category">${options(item.category)}</select></label>
        <label>Detail ${i + 1} title<input data-field="title" maxlength="120" required value="${esc(item.title)}" /></label>
        <label>Detail ${i + 1} description<textarea data-field="detail" rows="4" maxlength="3000" required>${esc(item.detail)}</textarea></label>
        ${item.quote ? `<details><summary>Original wording</summary><blockquote>${esc(item.quote)}</blockquote></details>` : ""}
      </article>`,
          )
          .join("")
      : '<p class="muted">No experience details confirmed yet. Add a draft from your conversation, or write one yourself.</p>';
  }

  function updateAssist() {
    $("#interview-assist").disabled =
      busy || !interview?.brigade_available || !$("#share-interview").checked;
  }

  function setBusy(value) {
    busy = value;
    $("#story-answer-form button").disabled = value || !interview;
    $("#clear-conversation").disabled = value || !interview;
    $("#resume-file").disabled = value || !interview;
    $("#story-suggestions")
      .querySelectorAll("button")
      .forEach((button) => {
        button.disabled = value;
      });
    updateAssist();
  }

  async function loadInterview() {
    const version = ++loadVersion;
    const result = await api("interview");
    if (version !== loadVersion) return;
    interview = result;
    renderInterview();
    setBusy(busy);
  }

  function renderInterview() {
    $("#story-question").textContent = interview.question.text;
    $("#question-source").textContent =
      interview.question_source === "brigade"
        ? "BRIGADE FOLLOW-UP"
        : "GUIDED QUESTION";
    $("#story-progress").textContent =
      `${interview.messages.filter((m) => m.role === "user").length} answers · ${background.length} profile details`;
    $("#message-count").textContent = `(${interview.messages.length})`;
    $("#story-messages").innerHTML = interview.messages
      .map((message) =>
        message.role === "resume"
          ? `<details class="story-message"><summary>Imported CV · stored locally</summary><p>${esc(message.text)}</p></details>`
          : `<div class="story-message ${message.role}"><strong>${message.role === "user" ? "You" : "Question"}</strong><p>${esc(message.text)}</p></div>`,
      )
      .join("");
    $("#interview-setup").hidden = interview.brigade_available;
    const available = interview.suggestions.filter(
      (s) => !background.some((b) => b.id === s.id),
    );
    $("#suggestion-count").textContent = available.length;
    $("#story-suggestions").innerHTML = available.length
      ? available
          .map(
            (item) => `
      <article class="suggestion-card" data-suggestion="${esc(item.id)}">
        <div class="fact-heading"><span class="tag">${esc(item.category)}</span><small>${esc(item.origin)}</small></div>
        <h3>${esc(item.title)}</h3><p>${esc(item.detail)}</p>
        <details><summary>What you said</summary><blockquote>${esc(item.quote)}</blockquote></details>
        <div class="suggestion-actions"><button type="button" class="text-button" data-accept="${esc(item.id)}">Add to profile draft →</button><button type="button" class="text-button" data-dismiss-suggestion="${esc(item.id)}">Dismiss suggestion</button></div>
      </article>`,
          )
          .join("")
      : '<p class="muted">Answer a question to capture a useful detail. Brigade can also suggest details from an imported CV. Added details are editable below.</p>';
    updateAssist();
  }

  $("#story-answer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    action(async () => {
      if (busy) return;
      setBusy(true);
      try {
        await api("interview/answer", {
          method: "POST",
          body: {
            revision: interview.revision,
            text: $("#story-answer").value,
          },
        });
        $("#story-answer").value = "";
        await loadInterview();
        $("#interview-status").textContent =
          "Answer saved locally. Review the new detail, or keep exploring.";
        $("#story-answer").focus();
      } catch (error) {
        await loadInterview();
        throw error;
      } finally {
        setBusy(false);
      }
    });
  });

  $("#share-interview").addEventListener("change", updateAssist);
  $("#interview-assist").addEventListener("click", () =>
    action(async () => {
      if (busy || !$("#share-interview").checked) return;
      setBusy(true);
      $("#interview-status").textContent =
        "Brigade is reading your experience and preparing a follow-up. This may take a couple of minutes.";
      try {
        await api("interview/assist", {
          method: "POST",
          body: { revision: interview.revision, share_with_model: true },
        });
        await loadInterview();
        $("#interview-status").textContent =
          "Brigade’s suggestions are ready. Check the wording and evidence before adding them.";
      } catch (error) {
        await loadInterview();
        $("#interview-status").textContent = error.message;
        throw error;
      } finally {
        $("#share-interview").checked = false;
        setBusy(false);
      }
    }),
  );

  $("#clear-conversation").addEventListener("click", () =>
    action(async () => {
      if (
        !window.confirm(
          "Clear this conversation, imported CV text, and unconfirmed suggestions? Saved profile details will stay.",
        )
      )
        return;
      await api(`interview?revision=${interview.revision}`, {
        method: "DELETE",
      });
      await loadInterview();
      $("#interview-status").textContent =
        "Conversation cleared. Your saved profile is unchanged.";
    }),
  );

  $("#story-suggestions").addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || busy) return;
    if (target.dataset.accept) {
      if (background.length >= 60) {
        notify(
          "Your profile supports up to 60 details. Edit or remove a detail first.",
          true,
        );
        return;
      }
      const item = interview.suggestions.find(
        (s) => s.id === target.dataset.accept,
      );
      background.push({
        id: item.id,
        category: item.category,
        title: item.title,
        detail: item.detail,
        quote: item.quote,
      });
      renderBackground();
      renderInterview();
      $("#interview-status").textContent =
        "Added to your editable profile below. Save your profile to confirm it.";
    }
    if (target.dataset.dismissSuggestion)
      action(async () => {
        await api(
          `interview/suggestions/${target.dataset.dismissSuggestion}?revision=${interview.revision}`,
          { method: "DELETE" },
        );
        await loadInterview();
      });
  });

  $("#background-items").addEventListener("input", (event) => {
    const card = event.target.closest("[data-background]");
    if (!card || !event.target.dataset.field) return;
    background.find((item) => item.id === card.dataset.background)[
      event.target.dataset.field
    ] = event.target.value;
    card.querySelector(".tag").textContent = "Edited · save profile to confirm";
  });
  $("#background-items").addEventListener("click", (event) => {
    const target = event.target.closest("[data-remove]");
    if (!target) return;
    background = background.filter((item) => item.id !== target.dataset.remove);
    renderBackground();
    if (interview) renderInterview();
  });
  $("#add-background").addEventListener("click", () => {
    if (background.length >= 60) {
      notify("Your profile supports up to 60 details.", true);
      return;
    }
    background.push({
      id: crypto.randomUUID(),
      category: "experience",
      title: "",
      detail: "",
      quote: "",
    });
    renderBackground();
    $("#background-items").lastElementChild.querySelector("input").focus();
  });

  setBusy(false);

  return {
    loadInterview,
    setBusy,
    isBusy: () => busy,
    revision: () => interview?.revision ?? 0,
    profileBackground: () => background,
    setProfile(profile) {
      background = structuredClone(profile.background || []);
      confirmed = new Set(background.map((item) => item.id));
      renderBackground();
      if (interview) renderInterview();
    },
    reset() {
      loadVersion++;
      interview = undefined;
      setBusy(false);
      $("#story-answer").value = "";
      $("#share-interview").checked = false;
      $("#interview-status").textContent = "";
    },
  };
}
