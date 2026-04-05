import { createContext, useContext, useState, ReactNode } from "react";

interface DemoContextType {
  isDemo: boolean;
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
  toggleDemo: () => void;
}

const DemoContext = createContext<DemoContextType>({
  isDemo: true,
  apiBaseUrl: "",
  setApiBaseUrl: () => {},
  toggleDemo: () => {},
});

export function DemoProvider({ children }: { children: ReactNode }) {
  const [apiBaseUrl, setApiBaseUrl] = useState(() =>
    localStorage.getItem("pbs-api-url") || ""
  );
  const [isDemo, setIsDemo] = useState(() => {
    const saved = localStorage.getItem("pbs-api-url");
    if (saved !== null) return !saved;  // user explicitly set a URL (or cleared it)
    return !import.meta.env.PROD;       // production = live mode, dev = demo mode
  });

  const handleSetUrl = (url: string) => {
    setApiBaseUrl(url);
    localStorage.setItem("pbs-api-url", url);
    setIsDemo(!url);
  };

  const toggleDemo = () => {
    if (isDemo && apiBaseUrl) {
      setIsDemo(false);
    } else {
      setIsDemo(true);
    }
  };

  return (
    <DemoContext.Provider value={{ isDemo, apiBaseUrl, setApiBaseUrl: handleSetUrl, toggleDemo }}>
      {children}
    </DemoContext.Provider>
  );
}

export const useDemo = () => useContext(DemoContext);
