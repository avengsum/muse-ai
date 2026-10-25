import { Alert, Linking, Platform } from "react-native";
import Constants from "expo-constants";

const isAndroidExpoGo =
  Platform.OS === "android" && Constants.appOwnership === "expo";

function getContactsModule() {
  if (Platform.OS === "web") return null;
  try {
    return require("expo-contacts");
  } catch {
    return null;
  }
}

function getNotificationsModule() {
  if (Platform.OS === "web" || isAndroidExpoGo) return null;
  try {
    return require("expo-notifications");
  } catch {
    return null;
  }
}

export async function findContactPhoneNumber(contactName) {
  const Contacts = getContactsModule();
  if (!Contacts) {
    return null;
  }

  const { status } = await Contacts.requestPermissionsAsync();
  if (status !== "granted") {
    throw new Error("Contacts permission is required to place calls.");
  }

  const { data } = await Contacts.getContactsAsync({
    fields: [Contacts.Fields.PhoneNumbers, Contacts.Fields.Name],
  });

  const target = String(contactName || "").trim().toLowerCase();
  if (!target || !Array.isArray(data)) {
    return null;
  }

  const match = data.find((c) => {
    const name = String(c.name || "").toLowerCase();
    return (
      name.includes(target) &&
      Array.isArray(c.phoneNumbers) &&
      c.phoneNumbers.length > 0
    );
  });

  if (!match) {
    return null;
  }

  return {
    name: match.name || contactName,
    phoneNumber: match.phoneNumbers[0].number,
  };
}

export async function placePhoneCall(phoneNumber) {
  const cleanNumber = String(phoneNumber || "").replace(/[^\d+]/g, "");
  if (!cleanNumber) {
    throw new Error("Invalid phone number.");
  }
  await Linking.openURL("tel:" + cleanNumber);
}

export async function scheduleCallReminder(name, phoneNumber, targetDate) {
  const Notifications = getNotificationsModule();
  if (!Notifications) {
    Alert.alert(
      "Reminder Set",
      "Call reminder for " +
        String(name) +
        " (" +
        String(phoneNumber) +
        ") at " +
        targetDate.toLocaleTimeString()
    );
    return;
  }

  await Notifications.scheduleNotificationAsync({
    content: {
      title: "Call " + String(name),
      body: "Tap to call " + String(phoneNumber),
      data: { url: "tel:" + String(phoneNumber) },
    },
    trigger: targetDate,
  });
}
