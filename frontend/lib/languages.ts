// The languages a run can be explained in, and the fixed words the screens need
// in each, so showing them costs no translation call.
export type LanguageCode = "hi" | "mr";

type Language = {
  code: LanguageCode;
  label: string;
  english: string;
  yes: string;
  no: string;
  notLegalAdvice: string;
  askHeading: string;
  explainedHeading: string;
  listen: string;
  tabs: { understand: string; rights: string; ask: string; document: string };
  suggestions: string[];
};

export const LANGUAGES: Language[] = [
  {
    code: "hi",
    label: "हिन्दी",
    english: "Hindi",
    yes: "हाँ",
    no: "नहीं",
    notLegalAdvice:
      "यह कानूनी सलाह नहीं है। कोई भी निर्णय लेने से पहले संबंधित कार्यालय से पुष्टि कर लें।",
    askHeading: "इस दस्तावेज़ के बारे में पूछें",
    explainedHeading: "आपके लिए सरल भाषा में",
    listen: "पूरी बात सुनें",
    tabs: { understand: "समझें", rights: "आपके हक़", ask: "पूछें", document: "दस्तावेज़" },
    suggestions: [
      "मुझे क्या लाभ मिलेगा?",
      "कौन आवेदन कर सकता है?",
      "कौन से कागज़ात चाहिए?",
      "आवेदन कहाँ करें?",
    ],
  },
  {
    code: "mr",
    label: "मराठी",
    english: "Marathi",
    yes: "हो",
    no: "नाही",
    notLegalAdvice:
      "हा कायदेशीर सल्ला नाही. कोणताही निर्णय घेण्यापूर्वी संबंधित कार्यालयाकडून खात्री करून घ्या.",
    askHeading: "या दस्तऐवजाबद्दल विचारा",
    explainedHeading: "तुमच्यासाठी सोप्या भाषेत",
    listen: "संपूर्ण माहिती ऐका",
    tabs: { understand: "समजून घ्या", rights: "तुमचे हक्क", ask: "विचारा", document: "दस्तऐवज" },
    suggestions: [
      "मला काय लाभ मिळेल?",
      "कोण अर्ज करू शकते?",
      "कोणती कागदपत्रे लागतात?",
      "अर्ज कुठे करायचा?",
    ],
  },
];

export function languageOf(code: string | undefined): Language {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
}
