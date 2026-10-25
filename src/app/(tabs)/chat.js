import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import * as api from "../../services/api";
import {
  confirmSchedule,
  confirmFoodOrder,
  cancelFoodOrder,
  getBrowserRun,
  getAgentRun,
  getAgentRunEvents,
  getConversationMessages,
  resumeBrowserRun,
  sendChatMessageStream,
  updateScheduleMessage,
} from "../../services/api";
import ChatInput from "../../components/ChatInput";
import ConversationSkeleton from "../../components/ConversationSkeleton";
import MessageBubble from "../../components/MessageBubble";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import {
  findContactPhoneNumber,
  placePhoneCall,
  scheduleCallReminder,
} from "../../services/phoneCallService";

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export default function ChatScreen() {
  const { colors } = useAppTheme();
  const {
    conversationId,
    setConversationId,
    refreshConversations,
    messageRefreshKey,
    agentName = "Cooper",
    accentColor = "#2563EB",
  } = useConversation();

  const startingMessages = useMemo(
    () => [
      {
        id: "welcome-message",
        sender: "agent",
        text:
          "Hi, I'm " +
          String(agentName) +
          ", your autonomous personal assistant. What goal can I handle for you today?",
      },
    ],
    [agentName]
  );

  const [messages, setMessages] = useState(startingMessages);
  const [inputText, setInputText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [resumingRunId, setResumingRunId] = useState(null);
  const [isConversationLoading, setIsConversationLoading] = useState(
    Boolean(conversationId)
  );
  const [loadedConversationId, setLoadedConversationId] = useState(null);
  const [historyLoadError, setHistoryLoadError] = useState("");
  const [historyRetryKey, setHistoryRetryKey] = useState(0);
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const containerRef = useRef(null);
  const messageListRef = useRef(null);
  const requestControllerRef = useRef(null);
  const historyRequestIdRef = useRef(0);
  const loadedConversationIdRef = useRef(null);
  const handledPrefillRef = useRef("");
  const handleAutoResumeConnectRef = useRef(null);
  const activeRunIdRef = useRef(null);
  const { prefill, conversation_id: routeConversationId } = useLocalSearchParams();


  useEffect(() => {
    const targetId = Array.isArray(routeConversationId)
      ? routeConversationId[0]
      : routeConversationId;
    if (targetId && targetId !== conversationId) {
      setConversationId(String(targetId));
    }
  }, [routeConversationId]);

  useEffect(() => {
    const nextPrefill = Array.isArray(prefill) ? prefill[0] : prefill;

    if (nextPrefill && nextPrefill !== handledPrefillRef.current) {
      handledPrefillRef.current = nextPrefill;
      setInputText(nextPrefill);
    }
  }, [prefill]);

  const isConversationChanging =
    Boolean(conversationId) &&
    (isConversationLoading || loadedConversationId !== conversationId);

  const fetchAndSetMessages = useCallback(
    async (targetConversationId, shouldUpdate = true) => {
      const savedMessages = await getConversationMessages(targetConversationId);
      const canUpdate =
        typeof shouldUpdate === "function" ? shouldUpdate() : shouldUpdate;

      if (!canUpdate) return false;

      setMessages(
        savedMessages.length > 0
          ? savedMessages.map((message) => ({
              id: String(message.id),
              sender: message.sender,
              text: message.text,
              browser: message.browser,
              sandbox: message.sandbox,
              scheduleConfirmation: message.schedule_confirmation,
              scheduleStatus: message.schedule_status,
              connectCta: message.connect_cta,
              swiggyCta: message.swiggy_cta,
              foodConfirmation: message.food_confirmation,
              foodStatus: message.food_status,
              foodOrderId: message.food_order_id,
              toolApproval: message.tool_approval,
              toolApprovalStatus: message.tool_approval_status,
              activity: message.activity ? message.activity : [],
              scratchpad: message.scratchpad ? message.scratchpad : null,
              activeSpecialist: message.active_specialist
                ? message.active_specialist
                : null,
            }))
          : startingMessages
      );
      return true;
    },
    [startingMessages]
  );

  useEffect(() => {
    let isActive = true;
    const requestId = historyRequestIdRef.current + 1;
    historyRequestIdRef.current = requestId;

    if (requestControllerRef.current) {
      requestControllerRef.current.abort();
      requestControllerRef.current = null;
    }

    if (!conversationId) {
      loadedConversationIdRef.current = null;
      setLoadedConversationId(null);
      setIsConversationLoading(false);
      setHistoryLoadError("");

      const timer = setTimeout(() => {
        if (isActive) {
          setIsSending(false);
          setStatusText("");
          setMessages(startingMessages);
        }
      }, 0);

      return () => {
        isActive = false;
        clearTimeout(timer);
      };
    }

    const targetConversationId = conversationId;
    const isNewConversation =
      loadedConversationIdRef.current !== targetConversationId;

    if (isNewConversation) {
      setIsConversationLoading(true);
      setHistoryLoadError("");
    }

    async function loadMessages() {
      if (isActive) {
        setIsSending(false);
        setStatusText("");
      }

      try {
        const didUpdate = await fetchAndSetMessages(
          targetConversationId,
          () =>
            isActive && historyRequestIdRef.current === requestId
        );

        if (didUpdate) {
          loadedConversationIdRef.current = targetConversationId;
          setLoadedConversationId(targetConversationId);
          setHistoryLoadError("");
        }
      } catch (error) {
        if (isActive && historyRequestIdRef.current === requestId) {
          const errorMessage =
            error && error.message
              ? error.message
              : "Could not load chat history";

          if (isNewConversation) {
            loadedConversationIdRef.current = targetConversationId;
            setLoadedConversationId(targetConversationId);
            setMessages([]);
            setHistoryLoadError(errorMessage);
          } else {
            setStatusText(errorMessage);
          }
        }
      } finally {
        if (isActive && historyRequestIdRef.current === requestId) {
          setIsConversationLoading(false);
        }
      }
    }

    loadMessages();

    return () => {
      isActive = false;
    };
  }, [
    conversationId,
    messageRefreshKey,
    historyRetryKey,
    fetchAndSetMessages,
    startingMessages,
  ]);

    useEffect(() => {
    if (Platform.OS !== "android") {
      return undefined;
    }

    const showSub = Keyboard.addListener("keyboardDidShow", (event) => {
      const kbHeight = event.endCoordinates?.height || 0;
      const screenHeight = Dimensions.get("window").height;
      const kbTopY =
        event.endCoordinates?.screenY || screenHeight - kbHeight;

      if (
        containerRef.current &&
        typeof containerRef.current.measureInWindow === "function"
      ) {
        containerRef.current.measureInWindow((_x, y, _width, height) => {
          const containerBottom = y + height;
          const overlap = Math.max(0, containerBottom - kbTopY);
          setKeyboardOffset(overlap > 0 ? overlap + 8 : kbHeight);
          setTimeout(() => scrollToLatestMessage(), 60);
        });
      } else {
        setKeyboardOffset(kbHeight);
        setTimeout(() => scrollToLatestMessage(), 60);
      }
    });

    const hideSub = Keyboard.addListener("keyboardDidHide", () => {
      setKeyboardOffset(0);
    });

    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  useEffect(() => {
    return () => {
      if (requestControllerRef.current) {
        requestControllerRef.current.abort();
      }
    };
  }, []);

  useEffect(() => {
    const subscription = Linking.addEventListener("url", ({ url }) => {
      if (
        url &&
        (url.includes("/chat") ||
          url.includes("/tools") ||
          url.includes("/swiggy/callback"))
      ) {
        const pendingConnectMsg = [...messages]
          .reverse()
          .find((m) => m.connectCta || m.swiggyCta);
        if (pendingConnectMsg && handleAutoResumeConnectRef.current) {
          handleAutoResumeConnectRef.current(
            pendingConnectMsg,
            Boolean(pendingConnectMsg.swiggyCta)
          );
        }
      }
    });

    return () => subscription.remove();
  }, [messages]);

  function updateAgentMessage(messageId, updater) {
    setMessages((currentMessages) =>
      currentMessages.map((message) => {
        if (message.id !== messageId) return message;
        const changes =
          typeof updater === "function" ? updater(message) : updater;
        return {
          ...message,
          ...changes,
        };
      })
    );
  }

  function pushActivityStep(messageId, stepText) {
    if (!stepText) return;
    setStatusText(stepText);
    updateAgentMessage(messageId, (msg) => {
      const existing = Array.isArray(msg.activity) ? msg.activity : [];
      if (existing[existing.length - 1] === stepText) {
        return {};
      }
      return {
        activity: [...existing, stepText].slice(-8),
      };
    });
  }

  function mergeActionText(existingText, actionText) {
    const cleanExisting = String(existingText ? existingText : "").trim();
    const cleanAction = String(actionText ? actionText : "").trim();
    if (!cleanExisting) return cleanAction;
    if (!cleanAction || cleanExisting.includes(cleanAction)) {
      return cleanExisting;
    }
    return cleanExisting + "\n\n" + cleanAction;
  }

  async function handleSend(explicitText) {
    const rawText = typeof explicitText === "string" ? explicitText : inputText;
    const cleanText = rawText.trim();

    if (
      !cleanText ||
      isSending ||
      isConversationChanging ||
      historyLoadError
    ) {
      return;
    }

    const currentTime = Date.now();
    const agentMessageId = "agent-" + String(currentTime);
    const userMessage = {
      id: "user-" + String(currentTime),
      sender: "user",
      text: cleanText,
    };

    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
      {
        id: agentMessageId,
        sender: "agent",
        text: "",
        activity: [],
        scratchpad: null,
        activeSpecialist: null,
      },
    ]);
    if (typeof explicitText !== "string") {
      setInputText("");
    }
    setIsSending(true);
    setStatusText(String(agentName) + " is planning...");
    activeRunIdRef.current = null;
    setTimeout(() => scrollToLatestMessage(), 30);

    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      const completed = await sendChatMessageStream(
        {
          message: cleanText,
          conversation_id: conversationId,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          callback_url: Linking.createURL("/chat"),
        },
        {
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === "run" && event.run_id) {
              activeRunIdRef.current = event.run_id;
              if (event.conversation_id && !conversationId) {
                import("@react-native-async-storage/async-storage").then(
                  ({ default: AsyncStorage }) =>
                    AsyncStorage.setItem(
                      "muse_active_conversation_id",
                      String(event.conversation_id)
                    )
                );
              }
            } else if (event.type === "scratchpad_updated") {
              const specLabel = event.name ? event.name : event.agent;
              pushActivityStep(
                agentMessageId,
                "Switched to " + String(specLabel)
              );
              updateAgentMessage(agentMessageId, {
                activeSpecialist: specLabel,
              });
            } else if (
              event.type === "tool_started" ||
              event.type === "tool_finished"
            ) {
              if (event.message) {
                pushActivityStep(agentMessageId, event.message);
              }
            } else if (event.type === "sandbox") {
              updateAgentMessage(agentMessageId, {
                sandbox: event.sandbox ? event.sandbox : event,
              });
            } else if (event.type === "tool_approval_request") {
              updateAgentMessage(agentMessageId, (msg) => ({
                text: mergeActionText(
                  msg.text,
                  event.output ? event.output : event.message
                ),
                toolApproval: event.tool_approval,
                toolApprovalStatus: "pending",
              }));
            }
          },
          onDelta: (textPart) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: (msg.text ? msg.text : "") + textPart,
            }));
          },
          onStatus: (event) => {
            pushActivityStep(
              agentMessageId,
              event.message
                ? event.message
                : String(agentName) + " is working..."
            );
          },
          onBrowser: (browser) => {
            updateAgentMessage(agentMessageId, { browser });
          },
          onSandbox: (sandbox) => {
            updateAgentMessage(agentMessageId, { sandbox });
          },
          onApprovalRequired: (event) => {
            setStatusText(
              event.message ? event.message : "The browser needs your input"
            );
            updateAgentMessage(agentMessageId, (msg) => ({
              browser: msg.browser
                ? {
                    ...msg.browser,
                    status: "paused",
                  }
                : msg.browser,
            }));
          },
          onScheduleConfirmation: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: mergeActionText(
                msg.text,
                event.output
                  ? event.output
                  : event.message
                  ? event.message
                  : "Schedule this task?"
              ),
              scheduleConfirmation: event.schedule_confirmation
                ? event.schedule_confirmation
                : event.confirmation,
              scheduleStatus: event.schedule_status
                ? event.schedule_status
                : "pending",
            }));
          },
          onCallAction: async (event) => {
            try {
              const contact = await findContactPhoneNumber(event.contact_name);

              if (!contact) {
                updateAgentMessage(agentMessageId, (msg) => ({
                  text: mergeActionText(
                    msg.text,
                    'I could not find "' +
                      String(event.contact_name) +
                      '" in your contacts.'
                  ),
                }));
                return;
              }

              if (String(event.call_time).toLowerCase() === "now") {
                updateAgentMessage(agentMessageId, (msg) => ({
                  text: mergeActionText(
                    msg.text,
                    "Calling " +
                      String(contact.name) +
                      " (" +
                      String(contact.phoneNumber) +
                      ")..."
                  ),
                }));
                await placePhoneCall(contact.phoneNumber);
                return;
              }

              const [hours, minutes] = String(event.call_time)
                .split(":")
                .map(Number);

              if (
                !Number.isInteger(hours) ||
                !Number.isInteger(minutes) ||
                hours < 0 ||
                hours > 23 ||
                minutes < 0 ||
                minutes > 59
              ) {
                throw new Error("I could not understand that call time.");
              }

              const targetDate = new Date();
              targetDate.setHours(hours, minutes, 0, 0);

              if (targetDate.getTime() <= Date.now()) {
                targetDate.setDate(targetDate.getDate() + 1);
              }

              await scheduleCallReminder(
                contact.name,
                contact.phoneNumber,
                targetDate
              );
              updateAgentMessage(agentMessageId, (msg) => ({
                text: mergeActionText(
                  msg.text,
                  "Scheduled a call reminder for " +
                    String(contact.name) +
                    " at " +
                    String(event.call_time) +
                    ". Tap the notification to call."
                ),
              }));
            } catch (error) {
              updateAgentMessage(agentMessageId, (msg) => ({
                text: mergeActionText(
                  msg.text,
                  error && error.message
                    ? error.message
                    : "I could not prepare that call."
                ),
              }));
            }
          },
          onConnectRequired: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              connectCta: event.connect_cta,
              text: mergeActionText(
                msg.text,
                event.output ? event.output : event.message
              ),
            }));
          },
          onSwiggyConnectRequired: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              swiggyCta: event.connect_cta,
              text: mergeActionText(
                msg.text,
                event.output ? event.output : event.message
              ),
            }));
          },
          onFoodOrderConfirmation: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: mergeActionText(
                msg.text,
                event.output
                  ? event.output
                  : event.message
                  ? event.message
                  : "Review your Swiggy order."
              ),
              foodConfirmation: event.food_confirmation,
              foodStatus: event.food_status ? event.food_status : "pending",
            }));
          },
          onToolApprovalRequest: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: mergeActionText(
                msg.text,
                event.output ? event.output : event.message
              ),
              toolApproval: event.tool_approval,
              toolApprovalStatus: "pending",
            }));
          },
          onDone: (event) => {
            if (event.message_id) {
              updateAgentMessage(agentMessageId, (msg) => ({
                id: String(event.message_id),
                text:
                  typeof event.output === "string" && event.output.trim()
                    ? event.output
                    : msg.text,
              }));
            }
          },
        }
      );

      const nextConversationId = completed ? completed.conversation_id : null;

      if (nextConversationId && nextConversationId !== conversationId) {
        setConversationId(nextConversationId);
      }

      refreshConversations();
    } catch (error) {
      if (
        (error && error.name === "AbortError") ||
        (error && error.message && error.message.includes("aborted")) ||
        (error && error.message && error.message.includes("canceled"))
      ) {
        return;
      }
      if (activeRunIdRef.current) {
        try {
          const recovered = await recoverAgentRun(
            activeRunIdRef.current,
            agentMessageId
          );
          if (recovered) {
            refreshConversations();
            return;
          }
        } catch {
          // Fall through
        }
      }
      updateAgentMessage(agentMessageId, (msg) => ({
        text: msg.text
          ? msg.text
          : error && error.message
          ? error.message
          : "I could not complete that request.",
      }));
    } finally {
      requestControllerRef.current = null;
      setIsSending(false);
      setStatusText("");
    }
  }

  async function triggerAgentReaction(systemEventText) {
    const currentTime = Date.now();
    const agentMessageId = "agent-" + String(currentTime);

    setMessages((currentMessages) => [
      ...currentMessages,
      {
        id: agentMessageId,
        sender: "agent",
        text: "",
        activity: [],
        scratchpad: null,
        activeSpecialist: null,
      },
    ]);
    setIsSending(true);
    setStatusText(String(agentName) + " is reacting...");

    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      await sendChatMessageStream(
        {
          message: systemEventText,
          conversation_id: conversationId,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          callback_url: Linking.createURL("/chat"),
        },
        {
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === "scratchpad_updated") {
              pushActivityStep(agentMessageId, event.message);
              updateAgentMessage(agentMessageId, {
                scratchpad: {
                  plan: event.plan ? event.plan : [],
                  currentStep: event.current_step ? event.current_step : 0,
                  notes: event.notes ? event.notes : "",
                },
              });
            } else if (event.type === "agent_switched") {
              updateAgentMessage(agentMessageId, {
                activeSpecialist: event.name ? event.name : event.agent,
              });
            } else if (
              (event.type === "tool_started" ||
                event.type === "tool_finished") &&
              event.message
            ) {
              pushActivityStep(agentMessageId, event.message);
            } else if (event.type === "sandbox") {
              updateAgentMessage(agentMessageId, {
                sandbox: event.sandbox ? event.sandbox : event,
              });
            } else if (event.type === "tool_approval_request") {
              updateAgentMessage(agentMessageId, (msg) => ({
                text: mergeActionText(
                  msg.text,
                  event.output ? event.output : event.message
                ),
                toolApproval: event.tool_approval,
                toolApprovalStatus: "pending",
              }));
            }
          },
          onDelta: (textPart) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: (msg.text ? msg.text : "") + textPart,
            }));
          },
          onStatus: (event) => {
            if (event.message) {
              pushActivityStep(agentMessageId, event.message);
            }
          },
          onFoodOrderConfirmation: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: mergeActionText(
                msg.text,
                event.output ? event.output : event.message
              ),
              foodConfirmation: event.food_confirmation,
              foodStatus: "pending",
            }));
          },
          onToolApprovalRequest: (event) => {
            updateAgentMessage(agentMessageId, (msg) => ({
              text: mergeActionText(
                msg.text,
                event.output ? event.output : event.message
              ),
              toolApproval: event.tool_approval,
              toolApprovalStatus: "pending",
            }));
          },
          onDone: (event) => {
            if (event.message_id) {
              updateAgentMessage(agentMessageId, (msg) => ({
                id: String(event.message_id),
                text:
                  typeof event.output === "string" && event.output.trim()
                    ? event.output
                    : msg.text,
              }));
            }
          },
        }
      );
      refreshConversations();
    } catch (err) {
      updateAgentMessage(agentMessageId, (msg) => ({
        text: msg.text
          ? msg.text
          : err && err.message
          ? err.message
          : "Action cancelled.",
      }));
    } finally {
      requestControllerRef.current = null;
      setIsSending(false);
      setStatusText("");
    }
  }

  async function recoverAgentRun(runId, agentMessageId) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const [run, events] = await Promise.all([
        getAgentRun(runId),
        getAgentRunEvents(runId),
      ]);
      const activity = events
        .filter((event) =>
          [
            "status",
            "tool_started",
            "tool_finished",
            "scratchpad_updated",
          ].includes(event.kind)
        )
        .map((event) => (event.payload ? event.payload.message : null))
        .filter(Boolean)
        .slice(-8);
      const done = events.find((event) => event.kind === "done");
      if (activity.length > 0) {
        updateAgentMessage(agentMessageId, { activity });
      }
      if (done) {
        if (done.payload && done.payload.conversation_id) {
          setConversationId(done.payload.conversation_id);
        }
        updateAgentMessage(agentMessageId, (msg) => ({
          text:
            done.payload && done.payload.output
              ? done.payload.output
              : msg.text
              ? msg.text
              : "Task completed.",
          id: String(
            done.payload && done.payload.message_id
              ? done.payload.message_id
              : agentMessageId
          ),
        }));
        return true;
      }
      if (["failed", "cancelled"].includes(run.status)) {
        throw new Error(run.error ? run.error : "The agent run failed");
      }
      await wait(1000);
    }
    return false;
  }

  function handleStop() {
    if (requestControllerRef.current) {
      requestControllerRef.current.abort();
      requestControllerRef.current = null;
    }
    setIsSending(false);
    setStatusText("");
  }

  async function handleResumeBrowser(runId) {
    if (resumingRunId) {
      return;
    }

    setResumingRunId(runId);
    setStatusText("Resuming browser...");

    try {
      let browser = await resumeBrowserRun(runId);

      for (let attempt = 0; attempt < 90; attempt += 1) {
        setMessages((currentMessages) =>
          currentMessages.map((message) =>
            message.browser && message.browser.id === runId
              ? {
                  ...message,
                  browser,
                }
              : message
          )
        );

        if (
          ["completed", "failed", "stopped", "timed_out"].includes(
            browser.status
          )
        ) {
          break;
        }

        setStatusText("Browser agent is working...");
        await wait(2000);
        browser = await getBrowserRun(runId);
      }

      if (conversationId && browser.status === "completed") {
        setStatusText(String(agentName) + " is finalizing results...");
        for (let poll = 0; poll < 8; poll += 1) {
          await wait(2000);
          await fetchAndSetMessages(conversationId, true);
        }
      }
    } catch (error) {
      setStatusText(
        error && error.message ? error.message : "Could not resume browser"
      );
      return;
    } finally {
      setResumingRunId(null);
    }

    setStatusText("");
  }

  async function handleConfirmSchedule(messageId) {
    const message = messages.find((item) => item.id === messageId);

    if (
      !message ||
      !message.scheduleConfirmation ||
      message.scheduleStatus !== "pending"
    ) {
      return;
    }

    updateAgentMessage(messageId, {
      scheduleStatus: "saving",
      scheduleError: null,
    });

    try {
      const task = await confirmSchedule(
        message.scheduleConfirmation,
        Number(messageId)
      );
      updateAgentMessage(messageId, (msg) => ({
        text: mergeActionText(
          msg.text,
          "✅ Scheduled: " +
            String(task.title) +
            " (" +
            String(task.schedule) +
            ")."
        ),
        scheduleStatus: "confirmed",
        scheduledTaskId: task.id,
      }));
      refreshConversations();
    } catch (error) {
      updateAgentMessage(messageId, {
        scheduleStatus: "pending",
        scheduleError:
          error && error.message
            ? error.message
            : "Could not create schedule",
      });
    }
  }

  async function handleCancelSchedule(messageId) {
    const message = messages.find((item) => item.id === messageId);

    if (
      !message ||
      !message.scheduleConfirmation ||
      message.scheduleStatus !== "pending"
    ) {
      return;
    }

    updateAgentMessage(messageId, {
      scheduleStatus: "cancelled",
    });

    try {
      await updateScheduleMessage(Number(messageId), "cancelled");
    } catch (error) {
      updateAgentMessage(messageId, {
        scheduleStatus: "pending",
        scheduleError:
          error && error.message
            ? error.message
            : "Could not cancel schedule",
      });
    }
  }

  function handleEditSchedule(messageId) {
    const message = messages.find((item) => item.id === messageId);

    if (!message || !message.scheduleConfirmation) {
      return;
    }

    setInputText(
      message.scheduleConfirmation.originalPrompt
        ? message.scheduleConfirmation.originalPrompt
        : ""
    );
    handleCancelSchedule(messageId);
  }

  async function handleConfirmFoodOrder(messageId, paymentMethod = "COD") {
    const message = messages.find((item) => item.id === messageId);

    if (
      !message ||
      !message.foodConfirmation ||
      !["pending", "pending_payment"].includes(message.foodStatus)
    ) {
      return;
    }

    updateAgentMessage(messageId, { foodStatus: "placing", foodError: null });

    try {
      if (paymentMethod === "VERIFY_UPI") {
        const check = await api.checkFoodPaymentStatus(Number(messageId));
        if (check.status === "placed") {
          updateAgentMessage(messageId, (msg) => ({
            text: mergeActionText(
              msg.text,
              `✅ UPI Payment received! Order placed on Swiggy (Order ID: ${check.order_id}).`
            ),
            foodStatus: "placed",
            foodOrderId: check.order_id,
          }));
          refreshConversations();
        } else {
          updateAgentMessage(messageId, {
            foodStatus: "pending_payment",
            foodError: "Payment is still pending. Please complete it in your UPI app and try again.",
          });
        }
        return;
      }

      const order = await confirmFoodOrder(Number(messageId), {
        paymentMethod,
        generateUpiQr: paymentMethod === "UPI",
      });

      if (order.status === "pending_payment") {
        updateAgentMessage(messageId, (msg) => ({
          foodStatus: "pending_payment",
          foodOrderId: order.order_id,
          foodConfirmation: {
            ...(msg.foodConfirmation ? msg.foodConfirmation : {}),
            upi_intent_url: order.upi_intent_url,
            qr_code: order.qr_code,
            order_id: order.order_id,
          },
        }));

        if (order.upi_intent_url && Platform.OS !== "web") {
          try {
            await Linking.openURL(order.upi_intent_url);
          } catch {
            // User can still scan QR or tap Open UPI App
          }
        }
        return;
      }

      updateAgentMessage(messageId, (msg) => ({
        text: mergeActionText(
          msg.text,
          "✅ Order placed on Swiggy (Order ID: " +
            String(order.order_id) +
            ")."
        ),
        foodStatus: "placed",
        foodOrderId: order.order_id,
      }));
      refreshConversations();
    } catch (error) {
      updateAgentMessage(messageId, {
        foodStatus: "pending",
        foodError:
          error && error.message
            ? error.message
            : "Could not place the Swiggy order",
      });
    }
  }

  async function handleCancelFoodOrder(messageId) {
    const message = messages.find((item) => item.id === messageId);

    if (
      !message ||
      !message.foodConfirmation ||
      message.foodStatus !== "pending"
    ) {
      return;
    }

    updateAgentMessage(messageId, {
      foodStatus: "cancelled",
      foodError: null,
    });

    try {
      await cancelFoodOrder(Number(messageId));
      await triggerAgentReaction(
        "[UI Event: User clicked Cancel on the prepared Swiggy food_order_confirmation card.]"
      );
    } catch (error) {
      updateAgentMessage(messageId, {
        foodStatus: "pending",
        foodError:
          error && error.message
            ? error.message
            : "Could not cancel the food order",
      });
    }
  }

  async function handleConfirmToolAction(messageId, editedArgs) {
    const message = messages.find((item) => item.id === messageId);
    if (
      !message ||
      !message.toolApproval ||
      message.toolApprovalStatus !== "pending"
    ) {
      return;
    }

    updateAgentMessage(messageId, {
      toolApprovalStatus: "executing",
      toolApprovalError: null,
    });

    try {
      const res =
        typeof api.confirmToolAction === "function"
          ? await api.confirmToolAction(Number(messageId), editedArgs)
          : { result: "Completed" };

      const appLabel = message.toolApproval.app_name || "Workspace";
      const actLabel =
        message.toolApproval.action_label || message.toolApproval.tool_name;
      const toolOutput =
        res && res.result ? String(res.result).slice(0, 1500) : "Success";

      updateAgentMessage(messageId, (msg) => ({
        text: mergeActionText(
          msg.text,
          `✅ Executed **${appLabel}: ${actLabel}**.`
        ),
        toolApprovalStatus: "completed",
        toolApproval: {
          ...msg.toolApproval,
          arguments: editedArgs || msg.toolApproval.arguments,
          result: toolOutput,
        },
      }));
      refreshConversations();

      // Wake the agent up with the tool output so it can run the next step or finish the reply!
      await triggerAgentReaction(
        `[UI Event: User approved and executed ${appLabel} (${actLabel}). Tool output: ${toolOutput}. If the user's request has remaining steps, execute the next step now; otherwise summarize the completed result.]`
      );
    } catch (error) {
      updateAgentMessage(messageId, {
        toolApprovalStatus: "pending",
        toolApprovalError:
          error && error.message ? error.message : "Could not run action",
      });
    }
  }

  async function handleCancelToolAction(messageId) {
    const message = messages.find((item) => item.id === messageId);
    if (
      !message ||
      !message.toolApproval ||
      message.toolApprovalStatus !== "pending"
    ) {
      return;
    }

    updateAgentMessage(messageId, {
      toolApprovalStatus: "cancelled",
      toolApprovalError: null,
    });

    try {
      if (typeof api.cancelToolAction === "function") {
        await api.cancelToolAction(Number(messageId));
      }
      await triggerAgentReaction(
        `[UI Event: User clicked Cancel on the ${
          message.toolApproval.tool_name || "workspace"
        } approval card.]`
      );
    } catch (error) {
      updateAgentMessage(messageId, {
        toolApprovalStatus: "pending",
        toolApprovalError:
          error && error.message ? error.message : "Could not cancel action",
      });
    }
  }

  async function handleAutoResumeConnect(message, isSwiggy = false) {
    handleAutoResumeConnectRef.current = handleAutoResumeConnect;

    if (isSending) {
      return;
    }

    const toolName = isSwiggy
      ? "Swiggy"
      : message && message.connectCta && message.connectCta.toolName
      ? message.connectCta.toolName
      : "my account";

    const currentIdx = messages.findIndex(
      (item) => item.id === (message ? message.id : null)
    );
    let originalRequest = "";
    if (currentIdx > 0) {
      for (let i = currentIdx - 1; i >= 0; i -= 1) {
        if (
          messages[i] &&
          messages[i].sender === "user" &&
          messages[i].text
        ) {
          originalRequest = messages[i].text.trim();
          break;
        }
      }
    }

    await wait(800);

    const resumePrompt = originalRequest
      ? "I have connected " +
        String(toolName) +
        '. Please complete: "' +
        String(originalRequest) +
        '".'
      : "I have connected " + String(toolName) + ". Please proceed.";

    await handleSend(resumePrompt);
  }

  function scrollToLatestMessage() {
    if (messageListRef.current) {
      messageListRef.current.scrollToEnd({ animated: false });
    }
  }

  function retryConversationLoad() {
    setHistoryLoadError("");
    setIsConversationLoading(true);
    setHistoryRetryKey((currentKey) => currentKey + 1);
  }

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: colors.background }]}
      ref={containerRef}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={Platform.OS === "ios" ? 95 : 0}
    >
      <ScrollView
        ref={messageListRef}
        style={{ flex: 1, backgroundColor: colors.background }}
        contentContainerStyle={styles.messageList}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
        onContentSizeChange={scrollToLatestMessage}
      >
        {isConversationChanging ? (
          <ConversationSkeleton />
        ) : historyLoadError ? (
          <View style={styles.historyErrorContainer}>
            <Text style={[styles.historyErrorTitle, { color: colors.text }]}>Conversation unavailable</Text>
            <Text style={[styles.historyErrorMessage, { color: colors.textSecondary }]}>{historyLoadError}</Text>
            <Pressable
              accessibilityRole="button"
              style={({ pressed }) => [
                styles.retryButton,
                { backgroundColor: colors.textStrong },
                pressed && styles.retryButtonPressed,
              ]}
              onPress={retryConversationLoad}
            >
              <Text style={[styles.retryButtonText, { color: colors.background }]}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={styles.dateContainer}>
              <View style={[styles.dateBadge, { backgroundColor: colors.surfaceTertiary }]}>
                <Text style={[styles.dateText, { color: colors.textSecondary }]}>Today</Text>
              </View>
            </View>

            {(conversationId ? messages : startingMessages).map((item) => (
              <MessageBubble
                key={item.id}
                message={item}
                onResumeBrowser={handleResumeBrowser}
                onConfirmSchedule={handleConfirmSchedule}
                onEditSchedule={handleEditSchedule}
                onCancelSchedule={handleCancelSchedule}
                onConfirmFoodOrder={handleConfirmFoodOrder}
                onCancelFoodOrder={handleCancelFoodOrder}
                onConfirmToolAction={handleConfirmToolAction}
                onCancelToolAction={handleCancelToolAction}
                onAutoResumeConnect={handleAutoResumeConnect}
              />
            ))}

            {isSending || resumingRunId ? (
              <View style={styles.typingRow}>
                <ActivityIndicator size="small" color={accentColor} />
                <Text style={[styles.typingText, { color: colors.textSecondary }]}>
                  {statusText
                    ? statusText
                    : String(agentName) + " is working..."}
                </Text>
              </View>
            ) : statusText ? (
              <Text style={[styles.errorText, { color: colors.danger }]}>{statusText}</Text>
            ) : null}
          </>
        )}
      </ScrollView>

      <ChatInput
        value={inputText}
        onChangeText={setInputText}
        onSend={handleSend}
        onStop={handleStop}
        isSending={isSending}
        disabled={isConversationChanging || Boolean(historyLoadError)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },
  messageList: {
    flexGrow: 1,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 10,
  },
  dateContainer: {
    alignItems: "center",
    marginVertical: 14,
  },
  dateBadge: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 12,
    backgroundColor: "#F3F4F6",
  },
  dateText: {
    color: "#888888",
    fontSize: 12,
    fontWeight: "600",
  },
  typingRow: {
    flexDirection: "row",
    alignItems: "center",
    marginVertical: 8,
  },
  typingText: {
    flex: 1,
    marginLeft: 8,
    color: "#64748B",
    fontSize: 13,
    fontStyle: "italic",
  },
  errorText: {
    marginVertical: 8,
    color: "#DC2626",
    fontSize: 13,
  },
  historyErrorContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 28,
    paddingVertical: 48,
  },
  historyErrorTitle: {
    color: "#1E293B",
    fontSize: 17,
    fontWeight: "700",
    textAlign: "center",
  },
  historyErrorMessage: {
    marginTop: 8,
    color: "#64748B",
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  retryButton: {
    marginTop: 18,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 18,
    backgroundColor: "#1E293B",
  },
  retryButtonPressed: {
    opacity: 0.78,
  },
  retryButtonText: {
    color: "#FFFFFF",
    fontSize: 14,
    fontWeight: "700",
  },
});
