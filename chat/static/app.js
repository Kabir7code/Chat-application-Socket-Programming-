"use strict";

const $ = (id) => document.getElementById(id);
const USERNAME_PATTERN = /^[A-Za-z0-9_]{1,20}$/;
const EVERYONE = "everyone";
const AVATAR_COLOURS = ["#5b3fd6", "#d6336c", "#0b7fab", "#c2410c", "#7c3aed", "#0f766e", "#be185d", "#4338ca"];
// Darker versions of the same idea, readable as sender names on a white bubble.
const NAME_COLOURS = ["#5b3fd6", "#c2255c", "#0b6f96", "#b23c09", "#6d28d9", "#0f766e", "#a3154f", "#3730a3"];

const state = {
  session: null,
  username: null,
  events: null,
  online: [],
  chats: new Map(), // chat key -> { key, kind, name, items, unread, members, lastAt }
  activeKey: EVERYONE,
  infoOpen: false,
  silentUserLists: 0, // list_users replies that only refresh the sidebar
  followNextSend: false, // a typed /msg or /g opens the chat it went to
  connected: false,
  activity: 0, // increases with each message, to sort chats by most recent
};

// ------------------------------------------------------------------- API
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { status: response.status, data };
}

async function send(message) {
  const { status, data } = await post("/api/send", { session: state.session, message });
  reportFailure(status, data);
}

async function runCommand(line) {
  state.followNextSend = /^\/(msg|g)\s/.test(line);
  const { status, data } = await post("/api/command", { session: state.session, line });
  if (reportFailure(status, data)) return;
  if (data.local) addToActive({ kind: "local", text: data.local });
  if (data.quit) showJoinScreen();
}

function reportFailure(status, data) {
  if (status === 200) return false;
  if (status === 404 || status === 502) markDisconnected();
  else addToActive({ kind: "error", text: data.error || "Request failed." });
  return true;
}

// ------------------------------------------------------------- join / leave
$("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("username").value.trim();
  if (!USERNAME_PATTERN.test(username)) {
    $("join-error").textContent = "Use 1-20 letters, digits or underscores.";
    return;
  }
  $("join-error").textContent = "";
  let reply;
  try {
    reply = await post("/api/connect", { username });
  } catch {
    $("join-error").textContent = "Could not reach the web gateway.";
    return;
  }
  if (reply.status !== 200) {
    $("join-error").textContent = reply.data.error || "Could not join.";
    return;
  }
  startChat(reply.data);
});

function startChat({ session, username, users, encrypted }) {
  Object.assign(state, {
    session, username, online: users, chats: new Map(), activeKey: EVERYONE,
    infoOpen: false, silentUserLists: 0, followNextSend: false, connected: true, activity: 0,
  });
  ensureChat(EVERYONE, "everyone", "Everyone");
  $("me").textContent = username;
  paintAvatar($("my-avatar"), username);
  $("security").textContent = encrypted ? "Encrypted (TLS)" : "Not encrypted";
  $("status").hidden = true;
  $("search").value = "";
  $("group-name").value = "";
  $("member-name").value = "";
  $("text").value = "";
  toggleNewGroup(false);
  $("join-screen").hidden = true;
  $("chat-screen").hidden = false;
  setSendingEnabled(true);
  openChat(EVERYONE);
  openEvents();
  refreshOnline();
  $("text").focus();
}

function openEvents() {
  const url = `/api/events?session=${encodeURIComponent(state.session)}`;
  state.events = new EventSource(url);
  state.events.onmessage = (event) => handleEvent(JSON.parse(event.data));
  state.events.onerror = markDisconnected;
}

function closeEvents() {
  if (state.events) state.events.close();
  state.events = null;
}

function markDisconnected() {
  if (!state.connected) return;
  state.connected = false;
  closeEvents();
  setSendingEnabled(false);
  $("status").textContent = "Disconnected from server";
  $("status").hidden = false;
}

function setSendingEnabled(enabled) {
  const controls = "#send-form input, #send-form button, #new-group input, #new-group button, " +
    "#new-group-toggle, #group-actions input, #group-actions button, #leave-group";
  document.querySelectorAll(controls).forEach((control) => { control.disabled = !enabled; });
}

function showJoinScreen() {
  state.connected = false;
  closeEvents();
  state.session = null;
  $("chat-screen").hidden = true;
  $("join-screen").hidden = false;
  $("username").focus();
}

$("leave").addEventListener("click", async () => {
  const session = state.session;
  closeEvents();
  showJoinScreen();
  if (session) await post("/api/disconnect", { session }).catch(() => {});
});

// Closing or reloading the tab leaves the chat straight away.
window.addEventListener("pagehide", () => {
  if (!state.session || !state.connected) return;
  const body = new Blob([JSON.stringify({ session: state.session })], { type: "application/json" });
  navigator.sendBeacon("/api/disconnect", body);
});

// ---------------------------------------------------------- incoming events
function handleEvent(message) {
  switch (message.type) {
    case "disconnected":
      markDisconnected();
      break;
    case "users":
      state.online = message.users;
      if (state.silentUserLists > 0) state.silentUserLists -= 1;
      else addToActive({ kind: "notice", text: message.display.replace(/^\* /, "") });
      renderChrome();
      break;
    case "system":
      addTo(EVERYONE, { kind: "notice", text: message.text }, { countUnread: false });
      refreshOnline();
      break;
    case "group_update":
      applyGroupUpdate(message);
      break;
    case "private":
      addTo(privateChat(message.from).key, bubble(message, false));
      break;
    case "private_sent":
      addTo(privateChat(message.to).key, bubble(message, true));
      followSend(`user:${message.to}`);
      break;
    case "chat":
      addChatMessage(message);
      break;
    case "error":
      state.followNextSend = false;
      addToActive({ kind: "error", text: message.message });
      break;
    default:
  }
}

function addChatMessage(message) {
  if (message.context !== "group") {
    addTo(EVERYONE, bubble(message, Boolean(message.self)));
    return;
  }
  const key = `group:${message.group}`;
  ensureChat(key, "group", message.group);
  addTo(key, bubble(message, Boolean(message.self)), { countUnread: !message.history });
  if (message.self) followSend(key);
}

function followSend(key) {
  if (state.followNextSend) {
    state.followNextSend = false;
    openChat(key);
  }
}

function bubble(message, mine) {
  return {
    kind: mine ? "mine" : "incoming",
    from: message.from,
    text: message.text,
    time: clockTime(message.time),
    history: Boolean(message.history),
    title: message.display,
  };
}

function clockTime(stamp) {
  const when = new Date(stamp);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function refreshOnline() {
  state.silentUserLists += 1;
  send({ type: "list_users" }).catch(markDisconnected);
}

function applyGroupUpdate({ group, members, username, event, text }) {
  const key = `group:${group}`;
  if (!members.includes(state.username)) {
    state.chats.delete(key);
    if (state.activeKey === key) {
      state.infoOpen = false;
      openChat(EVERYONE);
    }
    addTo(EVERYONE, { kind: "notice", text });
    return;
  }
  const chat = ensureChat(key, "group", group);
  chat.members = members;
  addTo(key, { kind: "notice", text }, { countUnread: false });
  // Opening a group you just created or joined; being added by someone else does not.
  if (username === state.username && (event === "created" || event === "joined")) {
    openChat(key);
    toggleNewGroup(false);
    $("group-name").value = "";
  }
}

// ---------------------------------------------------------------- chat data
function ensureChat(key, kind, name) {
  if (!state.chats.has(key)) {
    state.chats.set(key, { key, kind, name, items: [], unread: 0, members: [], lastAt: 0 });
  }
  return state.chats.get(key);
}

function privateChat(name) {
  return ensureChat(`user:${name}`, "user", name);
}

function addTo(key, item, { countUnread = true } = {}) {
  const chat = state.chats.get(key);
  if (!chat) return;
  chat.items.push(item);
  if (!item.passing) chat.lastAt = ++state.activity;
  const isOpen = key === state.activeKey;
  if (isOpen) appendToScreen(item, chat.items[chat.items.length - 2]);
  else if (countUnread) chat.unread += 1;
  renderChrome();
}

// Errors and command output belong to the moment, not to the conversation:
// they show in the open chat but do not change its preview or its place in the list.
function addToActive(item) {
  addTo(state.activeKey, { ...item, passing: true }, { countUnread: false });
}

function lastLasting(chat) {
  return [...chat.items].reverse().find((item) => !item.passing);
}

function openChat(key) {
  // A person in the Online list has no chat until it is first opened.
  if (key.startsWith("user:")) privateChat(key.slice(5));
  state.activeKey = key;
  state.chats.get(key).unread = 0;
  $("chat-screen").classList.add("chat-open");
  renderMessages();
  renderChrome();
}

// A chat row for everyone: Everyone first until other chats are newer, then
// by latest message, then people online who have not been talked to yet.
function chatRows() {
  const rows = new Map(state.chats);
  state.online.filter((name) => name !== state.username).forEach((name) => {
    const key = `user:${name}`;
    if (!rows.has(key)) rows.set(key, { key, kind: "user", name, items: [], unread: 0, lastAt: 0 });
  });
  const filter = $("search").value.trim().toLowerCase();
  return [...rows.values()]
    .filter((chat) => chat.name.toLowerCase().includes(filter))
    .sort((a, b) => (b.lastAt - a.lastAt) || a.name.localeCompare(b.name));
}

// ---------------------------------------------------------------- rendering
function hashOf(text) {
  return [...text].reduce((hash, letter) => (hash * 31 + letter.charCodeAt(0)) % 9973, 7);
}

function paintAvatar(element, name, online = false) {
  element.textContent = name.slice(0, 2).toUpperCase();
  element.style.background = AVATAR_COLOURS[hashOf(name) % AVATAR_COLOURS.length];
  element.classList.toggle("online", online);
}

function isOnline(name) {
  return state.online.includes(name);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // text only, never HTML
  return node;
}

function renderMessages() {
  const items = state.chats.get(state.activeKey).items;
  $("messages").replaceChildren();
  items.forEach((item, index) => appendToScreen(item, items[index - 1]));
}

function appendToScreen(item, previous) {
  const list = $("messages");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.append(messageRow(item, previous));
  if (atBottom || item.kind === "mine") list.scrollTop = list.scrollHeight;
}

function messageRow(item, previous) {
  const row = element("li", item.kind);
  if (item.kind !== "mine" && item.kind !== "incoming") {
    row.append(element("div", "pill", item.text));
    return row;
  }
  const sameSender = previous && previous.kind === item.kind && previous.from === item.from;
  if (sameSender) row.classList.add("same-sender");
  if (item.history) row.classList.add("history");
  const box = element("div", "bubble");
  box.title = item.title;
  if (item.history) box.append(element("span", "earlier", "(earlier)"));
  const showSender = item.kind === "incoming" && !sameSender &&
    state.chats.get(state.activeKey).kind !== "user";
  if (showSender) {
    const sender = element("span", "sender", item.from);
    sender.style.color = NAME_COLOURS[hashOf(item.from) % NAME_COLOURS.length];
    box.append(sender);
  }
  box.append(document.createTextNode(item.text), element("span", "time", item.time));
  row.append(box);
  return row;
}

function renderChrome() {
  renderChatList();
  renderChatHeader();
  renderInfo();
}

function previewOf(chat) {
  const last = lastLasting(chat);
  if (!last) return chat.kind === "user" ? "Tap to chat" : "";
  if (last.kind === "mine") return `You: ${last.text}`;
  if (last.kind === "incoming" && chat.kind !== "user") return `${last.from}: ${last.text}`;
  return last.text;
}

function renderChatList() {
  const rows = chatRows().map((chat) => {
    const item = element("li");
    const button = element("button", "chat-row");
    button.type = "button";
    button.dataset.key = chat.key;
    if (chat.key === state.activeKey) button.classList.add("active");
    button.addEventListener("click", () => {
      openChat(chat.key);
      $("text").focus();
    });

    const avatar = element("div", "avatar");
    paintAvatar(avatar, chat.name, chat.kind === "user" && isOnline(chat.name));

    const body = element("div", "row-body");
    const top = element("div", "row-line");
    top.append(element("span", "row-name", chat.name));
    const last = lastLasting(chat);
    if (last && last.time) top.append(element("span", "row-time", last.time));
    const bottom = element("div", "row-line");
    bottom.append(element("span", "row-preview", previewOf(chat)));
    if (chat.unread > 0) bottom.append(element("span", "unread", String(chat.unread)));
    body.append(top, bottom);

    button.append(avatar, body);
    item.append(button);
    return item;
  });
  if (rows.length === 0) rows.push(element("li", "no-chats", "No chats found"));
  $("chats").replaceChildren(...rows);
}

function subtitleOf(chat) {
  if (chat.kind === "user") return isOnline(chat.name) ? "online" : "offline";
  if (chat.kind === "group") return chat.members.join(", ");
  return `${state.online.length} online`;
}

function renderChatHeader() {
  const chat = state.chats.get(state.activeKey);
  $("chat-name").textContent = chat.name;
  $("chat-subtitle").textContent = subtitleOf(chat);
  paintAvatar($("chat-avatar"), chat.name, chat.kind === "user" && isOnline(chat.name));
}

function renderInfo() {
  const chat = state.chats.get(state.activeKey);
  $("info").hidden = !state.infoOpen;
  $("chat-screen").classList.toggle("info-open", state.infoOpen);
  if (!state.infoOpen) return;
  const isGroup = chat.kind === "group";
  paintAvatar($("info-avatar"), chat.name);
  $("info-name").textContent = chat.name;
  $("group-actions").hidden = !isGroup;
  $("leave-group").hidden = !isGroup;

  const names = chat.kind === "user" ? [] : (isGroup ? chat.members : state.online);
  $("members-title").textContent = chat.kind === "user"
    ? subtitleOf(chat)
    : `${names.length} ${isGroup ? "members" : "online"}`;
  $("members").replaceChildren(...names.map((name, index) => {
    const row = element("li", "member");
    const avatar = element("div", "avatar");
    paintAvatar(avatar, name);
    row.append(avatar, element("span", "member-name", name === state.username ? `${name} (you)` : name));
    // The server always keeps a group's admin first in its member list.
    if (isGroup && index === 0) row.append(element("span", "tag", "admin"));
    return row;
  }));
}

// ------------------------------------------------------------------ sending
$("send-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("text");
  const text = input.value;
  if (!text.trim() || !state.connected) return;
  input.value = "";
  const action = text.startsWith("/") ? runCommand(text) : send(messageFor(text));
  action.catch(markDisconnected);
});

function messageFor(text) {
  const chat = state.chats.get(state.activeKey);
  if (chat.kind === "user") return { type: "private", to: chat.name, text };
  if (chat.kind === "group") return { type: "group", group: chat.name, text };
  return { type: "chat", text };
}

// ------------------------------------------------------------ small actions
$("search").addEventListener("input", renderChatList);

$("back").addEventListener("click", () => $("chat-screen").classList.remove("chat-open"));

$("chat-title").addEventListener("click", () => {
  state.infoOpen = !state.infoOpen;
  renderInfo();
});

$("info-close").addEventListener("click", () => {
  state.infoOpen = false;
  renderInfo();
});

function toggleNewGroup(show) {
  $("new-group").hidden = !show;
  $("new-group-toggle").setAttribute("aria-expanded", String(show));
  if (show) $("group-name").focus();
}

$("new-group-toggle").addEventListener("click", () => toggleNewGroup($("new-group").hidden));

$("new-group").addEventListener("submit", (event) => {
  event.preventDefault();
  groupAction("create_group");
});

function groupAction(type) {
  const group = $("group-name").value.trim();
  if (!group) {
    $("group-name").focus();
    return;
  }
  send({ type, group }).catch(markDisconnected);
}

$("create-group").addEventListener("click", () => groupAction("create_group"));
$("join-group").addEventListener("click", () => groupAction("join_group"));

$("leave-group").addEventListener("click", () => {
  const chat = state.chats.get(state.activeKey);
  if (chat.kind === "group") send({ type: "leave_group", group: chat.name }).catch(markDisconnected);
});

$("add-member").addEventListener("click", () => {
  const chat = state.chats.get(state.activeKey);
  const username = $("member-name").value.trim();
  if (chat.kind !== "group" || !username) return;
  $("member-name").value = "";
  send({ type: "add_member", group: chat.name, username }).catch(markDisconnected);
});
