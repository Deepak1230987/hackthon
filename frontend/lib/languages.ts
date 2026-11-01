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
  },
];

export function languageOf(code: string | undefined): Language {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
}
