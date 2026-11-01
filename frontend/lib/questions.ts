import { languageOf } from "./languages.ts";
import type { Question } from "./types";

// Fixed text for the backend's field registry, so asking costs no translation
// call and the wording never changes between runs.
const QUESTIONS: Record<string, Record<string, string>> = {
  hi: {
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
  },
  mr: {
    age: "तुमचे वय किती आहे?",
    gender: "तुमचे लिंग कोणते आहे?",
    state: "तुम्ही कोणत्या राज्यात राहता?",
    district: "तुम्ही कोणत्या जिल्ह्यात राहता?",
    annual_income_inr: "तुमच्या कुटुंबाचे एका वर्षाचे एकूण उत्पन्न किती रुपये आहे?",
    occupation: "तुमचे मुख्य काम कोणते आहे?",
    social_category: "तुम्ही कोणत्या सामाजिक प्रवर्गातील आहात?",
    land_holding_hectares: "तुमच्याकडे किती हेक्टर जमीन आहे?",
    business_turnover_inr: "तुमच्या व्यवसायाची एका वर्षाची उलाढाल किती रुपये आहे?",
    employee_count: "तुमच्या व्यवसायात किती लोक काम करतात?",
    is_bpl: "तुमचे कुटुंब दारिद्र्यरेषेखाली आहे का?",
    is_student: "तुम्ही सध्या विद्यार्थी आहात का?",
    has_disability: "तुम्हाला काही दिव्यांगत्व आहे का?",
  },
};

const OPTIONS: Record<string, Record<string, string>> = {
  hi: {
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
  },
  mr: {
    female: "महिला",
    male: "पुरुष",
    other: "इतर",
    farmer: "शेतकरी",
    student: "विद्यार्थी",
    government_employee: "सरकारी कर्मचारी",
    salaried: "पगारदार",
    self_employed: "स्वयंरोजगार",
    daily_wage: "रोजंदारी कामगार",
    homemaker: "गृहिणी",
    retired: "सेवानिवृत्त",
    unemployed: "बेरोजगार",
    general: "सर्वसाधारण",
    obc: "इतर मागास वर्ग (OBC)",
    sc: "अनुसूचित जाती (SC)",
    st: "अनुसूचित जमाती (ST)",
    ews: "आर्थिकदृष्ट्या दुर्बल घटक (EWS)",
  },
};

const UNITS: Record<string, Record<string, string>> = {
  hi: { years: "साल", INR: "रुपये", hectares: "हेक्टेयर" },
  mr: { years: "वर्षे", INR: "रुपये", hectares: "हेक्टर" },
};

export function questionText(question: Question, language = "hi"): string {
  return QUESTIONS[language]?.[question.name] ?? question.question_en;
}

export function optionLabel(option: string, language = "hi"): string {
  return OPTIONS[language]?.[option] ?? option;
}

// What the citizen is asked to confirm, so a misheard answer is easy to spot.
export function answerLabel(
  question: Question,
  value: unknown,
  language = "hi",
): string {
  const words = languageOf(language);
  if (question.type === "bool") return value ? words.yes : words.no;
  if (question.type === "enum") return optionLabel(String(value), language);
  if (question.type === "int" || question.type === "float") {
    const amount = Number(value).toLocaleString("en-IN");
    const unit = question.unit ? UNITS[language]?.[question.unit] : undefined;
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
