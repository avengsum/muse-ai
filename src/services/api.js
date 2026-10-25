import { Platform } from "react-native";
import { fetch } from "expo/fetch";
import Constants from "expo-constants";
import { supabase } from "../lib/supabase";

const configuredApiUrl = process.env.EXPO_PUBLIC_API_URL
  ? process.env.EXPO_PUBLIC_API_URL.trim().replace(/\/+$/, "")
  : "";

function getExpoHost() {
  const candidates = [
    Constants.expoConfig ? Constants.expoConfig.hostUri : null,
    Constants.expoGoConfig ? Constants.expoGoConfig.debuggerHost : null,
    Constants.manifest2 &&
    Constants.manifest2.extra &&
    Constants.manifest2.extra.expoGo
      ? Constants.manifest2.extra.expoGo.debuggerHost
      : null,
    Constants.manifest ? Constants.manifest.debuggerHost : null,
    Constants.linkingUri,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      const cleaned = candidate.replace(/^[a-z]+:\/\//i, "").split("/")[0];
      const host = cleaned.split(":")[0];
      if (
        host &&
        host !== "localhost" &&
        host !== "127.0.0.1" &&
        !host.startsWith("192.168.56.") &&
        !host.startsWith("192.168.116.")
      ) {
        return host;
      }
    }
  }

  return "";
}

const detectedHost = getExpoHost();

export const API_BASE_URL = configuredApiUrl
  ? configuredApiUrl
  : Platform.OS !== "web" && detectedHost
  ? "http://" + detectedHost + ":8000"
  : Platform.OS === "android"
  ? "http://10.220.110.43:8000"
  : "http://127.0.0.1:8000";

function getPathId(value) {
  return encodeURIComponent(String(value));
}

async function readResponseData(response) {
  const text = await response.text();

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return {
      detail: text,
    };
  }
}

function getErrorMessage(data, fallback) {
  if (data && typeof data.detail === "string") {
    return data.detail;
  }

  if (data && typeof data.message === "string") {
    return data.message;
  }

  return fallback;
}

async function requestJson(path, options, fallback) {
  const response = await apiFetch(path, options);
  const data = await readResponseData(response);

  if (!response.ok) {
    throw new Error(getErrorMessage(data, fallback));
  }

  return data;
}

async function apiFetch(path, options = {}) {
  const headers = {
    ...(options.headers ? options.headers : {}),
  };

  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const accessToken =
      data && data.session ? data.session.access_token : null;

    if (accessToken) {
      headers.Authorization = "Bearer " + accessToken;
    }
  }

  return fetch(API_BASE_URL + path, {
    ...options,
    headers,
  });
}

export async function getConversationMessages(conversationId) {
  return requestJson(
    "/api/conversations/" + getPathId(conversationId) + "/messages",
    undefined,
    "Could not load messages"
  );
}

export async function sendChatMessageStream(
  payload,
  handlersOrOnDelta = {},
  requestOptions = {}
) {
  const handlers =
    typeof handlersOrOnDelta === "function"
      ? {
          ...requestOptions,
          onDelta: handlersOrOnDelta,
        }
      : {
          ...(handlersOrOnDelta ? handlersOrOnDelta : {}),
          ...requestOptions,
        };

  const response = await apiFetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
    },
    body: JSON.stringify(payload),
    signal: handlers.signal,
  });

  if (!response.ok) {
    const data = await readResponseData(response);

    throw new Error(getErrorMessage(data, "The backend returned an error"));
  }

  if (!response.body) {
    throw new Error("Streaming is unavailable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  let completedEvent = null;

  function processLine(line) {
    const cleanLine = line.trim();

    if (!cleanLine) {
      return;
    }

    let parsedEvent;

    try {
      parsedEvent = JSON.parse(cleanLine);
    } catch {
      throw new Error("The backend returned an invalid stream event");
    }

    if (handlers.onEvent) {
      handlers.onEvent(parsedEvent);
    }

    if (parsedEvent.type === "delta") {
      if (handlers.onDelta) {
        handlers.onDelta(
          parsedEvent.text ? parsedEvent.text : "",
          parsedEvent
        );
      }
    }

    if (
      parsedEvent.type === "status" ||
      parsedEvent.type === "tool_started" ||
      parsedEvent.type === "tool_finished" ||
      parsedEvent.type === "scratchpad_updated" ||
      parsedEvent.type === "agent_switched"
    ) {
      if (handlers.onStatus) {
        handlers.onStatus(parsedEvent);
      }
    }

    if (parsedEvent.type === "browser") {
      if (handlers.onBrowser) {
        handlers.onBrowser(
          parsedEvent.browser ? parsedEvent.browser : parsedEvent,
          parsedEvent
        );
      }
    }

    if (parsedEvent.type === "sandbox") {
      if (handlers.onSandbox) {
        handlers.onSandbox(
          parsedEvent.sandbox ? parsedEvent.sandbox : parsedEvent,
          parsedEvent
        );
      }
    }

    if (parsedEvent.type === "approval_required") {
      if (handlers.onApprovalRequired) {
        handlers.onApprovalRequired(parsedEvent);
      }
    }

    if (parsedEvent.type === "connect_required") {
      if (handlers.onConnectRequired) {
        handlers.onConnectRequired(parsedEvent);
      }
    }

    if (parsedEvent.type === "swiggy_connect_required") {
      if (handlers.onSwiggyConnectRequired) {
        handlers.onSwiggyConnectRequired(parsedEvent);
      }
    }

    if (parsedEvent.type === "food_order_confirmation") {
      if (handlers.onFoodOrderConfirmation) {
        handlers.onFoodOrderConfirmation(parsedEvent);
      }
    }

    if (parsedEvent.type === "schedule_confirmation") {
      if (handlers.onScheduleConfirmation) {
        handlers.onScheduleConfirmation({
          ...parsedEvent,
          schedule_confirmation: parsedEvent.schedule_confirmation
            ? parsedEvent.schedule_confirmation
            : parsedEvent.confirmation,
        });
      }
    }

    if (parsedEvent.type === "tool_approval_request") {
      if (handlers.onToolApprovalRequest) {
        handlers.onToolApprovalRequest(parsedEvent);
      }
    }

    

    if (parsedEvent.type === "call_action") {
      if (handlers.onCallAction) {
        handlers.onCallAction(parsedEvent);
      }
    }

    if (parsedEvent.type === "done" || parsedEvent.type === "final") {
      completedEvent = parsedEvent;
      if (handlers.onDone) {
        handlers.onDone(parsedEvent);
      }
    }

    if (parsedEvent.type === "error") {
      if (handlers.onError) {
        handlers.onError(parsedEvent);
      }
      throw new Error(
        parsedEvent.message ? parsedEvent.message : "The AI request failed"
      );
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, {
        stream: true,
      });

      const lines = buffer.split("\n");
      const lastPart = lines.pop();
      buffer = lastPart ? lastPart : "";

      for (const line of lines) {
        processLine(line);
        if (completedEvent) {
          break;
        }
      }

      if (completedEvent) {
        try {
          await reader.cancel();
        } catch {
          // Ignore cancellation errors
        }
        break;
      }
    }

    if (!completedEvent) {
      buffer += decoder.decode();

      if (buffer.trim()) {
        processLine(buffer);
      }
    }

    if (!completedEvent) {
      throw new Error("The agent stream ended before completion");
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Ignore release lock errors
    }
  }

  return completedEvent;
}

export async function getConversations() {
  return requestJson(
    "/api/conversations",
    undefined,
    "Could not load conversations"
  );
}

export async function getAgentRun(runId) {
  return requestJson(
    "/api/agent/runs/" + getPathId(runId),
    undefined,
    "Could not load agent run"
  );
}

export async function getAgentRunEvents(runId) {
  return requestJson(
    "/api/agent/runs/" + getPathId(runId) + "/events",
    undefined,
    "Could not load agent progress"
  );
}

export async function clearConversationMessages(conversationId) {
  return requestJson(
    "/api/conversations/" + getPathId(conversationId) + "/messages",
    {
      method: "DELETE",
    },
    "Could not clear conversation"
  );
}

export async function deleteConversation(conversationId) {
  return requestJson(
    "/api/conversations/" + getPathId(conversationId),
    {
      method: "DELETE",
    },
    "Could not delete conversation"
  );
}

export async function getBrowserRun(runId) {
  return requestJson(
    "/api/browser/runs/" + getPathId(runId),
    undefined,
    "Could not load browser run"
  );
}

export async function resumeBrowserRun(runId, message) {
  return requestJson(
    "/api/browser/runs/" + getPathId(runId) + "/resume",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: message
          ? message
          : "Continue now that the requested input is complete.",
      }),
    },
    "Could not resume browser run"
  );
}

export async function getTools() {
  return requestJson("/api/tools", undefined, "Could not load tools");
}

export async function connectTool(toolId, callbackUrl) {
  return requestJson(
    "/api/tools/" + getPathId(toolId) + "/connect",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        callback_url: callbackUrl,
      }),
    },
    "Could not connect tool"
  );
}

export async function disconnectTool(toolId) {
  return requestJson(
    "/api/tools/" + getPathId(toolId) + "/disconnect",
    {
      method: "POST",
    },
    "Could not disconnect tool"
  );
}

export async function getTasks() {
  return requestJson("/api/tasks", undefined, "Could not load tasks");
}

export async function getTaskRun(taskId, runId) {
  return requestJson(
    "/api/tasks/" + getPathId(taskId) + "/runs/" + getPathId(runId),
    undefined,
    "Could not load task result"
  );
}

export async function createTask(payload) {
  return requestJson(
    "/api/tasks",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    "Could not create task"
  );
}

export async function confirmSchedule(confirmation, sourceMessageId) {
  return requestJson(
    "/api/tasks/confirm",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        confirmation,
        source_message_id: sourceMessageId,
      }),
    },
    "Could not create schedule"
  );
}

export async function updateScheduleMessage(messageId, status) {
  return requestJson(
    "/api/messages/" + getPathId(messageId) + "/schedule",
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ status }),
    },
    "Could not update schedule"
  );
}

export async function updateTask(taskId, payload) {
  return requestJson(
    "/api/tasks/" + getPathId(taskId),
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    "Could not update task"
  );
}

export async function toggleTask(taskId) {
  return requestJson(
    "/api/tasks/" + getPathId(taskId) + "/toggle",
    {
      method: "PATCH",
    },
    "Could not update task"
  );
}

export async function runTask(taskId) {
  return requestJson(
    "/api/tasks/" + getPathId(taskId) + "/run",
    {
      method: "POST",
    },
    "Could not run task"
  );
}

export async function deleteTask(taskId) {
  return requestJson(
    "/api/tasks/" + getPathId(taskId),
    {
      method: "DELETE",
    },
    "Could not delete task"
  );
}

export async function getSettings() {
  return requestJson("/api/settings", undefined, "Could not load settings");
}

export async function saveSettings(payload) {
  return requestJson(
    "/api/settings",
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    "Could not save settings"
  );
}

export async function getUserMemories() {
  return requestJson(
    "/api/user/memories",
    undefined,
    "Could not load memories"
  );
}

export async function deleteUserMemory(memoryId) {
  return requestJson(
    "/api/user/memories/" + getPathId(memoryId),
    { method: "DELETE" },
    "Could not delete memory"
  );
}

export async function startSwiggyOAuth(callbackUrl) {
  return requestJson(
    "/api/swiggy/oauth/start?callback_url=" + encodeURIComponent(callbackUrl),
    undefined,
    "Could not start Swiggy authorization"
  );
}

export async function getSwiggyStatus() {
  return requestJson(
    "/api/swiggy/status",
    undefined,
    "Could not load Swiggy connection"
  );
}

export async function disconnectSwiggy() {
  return requestJson(
    "/api/swiggy/disconnect",
    { method: "POST" },
    "Could not disconnect Swiggy"
  );
}

export async function confirmFoodOrder(messageId, options = {}) {
  return requestJson(
    "/api/food/orders/" + getPathId(messageId) + "/confirm",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payment_method: options.paymentMethod ? options.paymentMethod : "COD",
        generate_upi_qr: Boolean(options.generateUpiQr),
        intent_app: options.intentApp ? options.intentApp : null,
      }),
    },
    "Could not place the Swiggy order"
  );
}

export async function checkFoodPaymentStatus(messageId) {
  return requestJson(
    "/api/food/orders/" + getPathId(messageId) + "/check-payment",
    { method: "POST" },
    "Could not verify UPI payment status"
  );
}

export async function cancelFoodOrder(messageId) {
  return requestJson(
    "/api/food/orders/" + getPathId(messageId) + "/cancel",
    { method: "POST" },
    "Could not cancel the food order"
  );
}

export async function registerPushToken(token, platform) {
  return requestJson(
    "/api/push-tokens",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, platform }),
    },
    "Could not register push notifications"
  );
}

export async function getNotifications() {
  return requestJson(
    "/api/notifications",
    undefined,
    "Could not load notifications"
  );
}

export async function markNotificationRead(notificationId) {
  return requestJson(
    "/api/notifications/" + getPathId(notificationId) + "/read",
    { method: "PATCH" },
    "Could not mark notification as read"
  );
}

export async function clearNotifications() {
  return requestJson(
    "/api/notifications",
    { method: "DELETE" },
    "Could not clear notifications"
  );
}

export async function renameConversation(conversationId, title) {
  return requestJson(
    "/api/conversations/" + getPathId(conversationId),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title }),
    },
    "Could not rename conversation"
  );
}


export async function confirmToolAction(messageId, editedArguments = null) {
  return requestJson(
    "/api/actions/" + getPathId(messageId) + "/confirm",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        arguments: editedArguments,
      }),
    },
    "Could not execute tool action"
  );
}

export async function cancelToolAction(messageId) {
  return requestJson(
    "/api/actions/" + getPathId(messageId) + "/cancel",
    { method: "POST" },
    "Could not cancel tool action"
  );
}

export async function getDailyIdeas(force = false) {
  const query = force ? "?force=true" : "";
  return requestJson(
    "/api/ideas/daily" + query,
    undefined,
    "Could not load daily ideas"
  );
}
