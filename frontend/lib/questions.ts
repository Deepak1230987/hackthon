import type { Question } from "./types";

// Fixed Hindi for the backend's field registry, so asking costs no translation
// call and the wording never changes between runs.
const QUESTIONS_HI: Record<string, string> = {
  age: "आपकी उम्र कितनी है?",
  gender: "आपका लिंग क्या है?",
  state: "आप किस राज्य में रहते हैं?",
  district: "आप किस ज़िले में रहते हैं?",
  annual_income_inr: "आपके परिवार की एक साल की कुल आय कितने रुपये है?",
  occupation: "आपका मुख्य काम क्या है?",
  social_category: "आप किस सामाजिक वर्ग से हैं?",
  land_holding_hectares: "आपके पास कितने हेक्टेयर ज़मीन है?",
  business_turnover_inr: "आपके व्यवसाय का एक साल का कारोबार कितने रुपये है?",
  employee_count: "आपके व्यवसाय में कितने लोग काम करते हैं?",
  is_bpl: "क्या आपका परिवार गरीबी रेखा से नीचे है?",
  is_student: "क्या आप अभी विद्यार्थी हैं?",
  has_disability: "क्या आपको कोई दिव्यांगता है?",
};

const OPTIONS_HI: Record<string, string> = {
  female: "महिला",
  male: "पुरुष",
  other: "अन्य",
  farmer: "किसान",
  student: "विद्यार्थी",
  government_employee: "सरकारी कर्मचारी",
  salaried: "वेतनभोगी",
  self_employed: "स्वरोज़गार",
  daily_wage: "दिहाड़ी मज़दूर",
  homemaker: "गृहिणी",
  retired: "सेवानिवृत्त",
  unemployed: "बेरोज़गार",
  general: "सामान्य",
  obc: "अन्य पिछड़ा वर्ग (OBC)",
  sc: "अनुसूचित जाति (SC)",
  st: "अनुसूचित जनजाति (ST)",
  ews: "आर्थिक रूप से कमज़ोर वर्ग (EWS)",
};

const UNITS_HI: Record<string, string> = {
  years: "साल",
  INR: "रुपये",
  hectares: "हेक्टेयर",
};

export function questionText(question: Question): string {
  return QUESTIONS_HI[question.name] ?? question.question_en;
}

export function optionLabel(option: string): string {
  return OPTIONS_HI[option] ?? option;
}

// What the citizen is asked to confirm, so a misheard answer is easy to spot.
export function answerLabel(question: Question, value: unknown): string {
  if (question.type === "bool") return value ? "हाँ" : "नहीं";
  if (question.type === "enum") return optionLabel(String(value));
  if (question.type === "int" || question.type === "float") {
    const amount = Number(value).toLocaleString("en-IN");
    const unit = question.unit ? UNITS_HI[question.unit] : undefined;
    return unit ? `${amount} ${unit}` : amount;
  }
  return String(value);
}

// A typed number may have Indian or western commas. Anything else stays as text,
// and the backend's range check gives the message.
export function typedValue(question: Question, typed: string): string | number {
  const text = typed.trim();
  if (question.type !== "int" && question.type !== "float") return text;
  const number = Number(text.replace(/,/g, ""));
  return text !== "" && Number.isFinite(number) ? number : text;
}
