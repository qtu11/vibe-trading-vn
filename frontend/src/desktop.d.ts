export {};

export interface DesktopCredentialStatus {
  available: boolean;
  configured: string[];
  migrated: string[];
}

export interface SourceBrowserState {
  url: string;
  title: string;
  loading: boolean;
  canGoBack: boolean;
  canGoForward: boolean;
  error?: string;
  closed?: boolean;
}

export interface SourceBrowserBounds { x: number; y: number; width: number; height: number }

declare global {
  interface Window {
    vibeDesktop?: {
      isDesktop: boolean;
      sourceBrowser?: {
        open: (url: string, bounds: SourceBrowserBounds) => Promise<void>;
        setBounds: (bounds: SourceBrowserBounds) => void;
        close: () => void;
        navigate: (action: "back" | "forward" | "reload") => void;
        openExternal: (url: string) => void;
        onState: (callback: (state: SourceBrowserState) => void) => () => void;
      };
      restartBackend: () => Promise<boolean>;
      getCredentialStatus: () => Promise<DesktopCredentialStatus>;
      setCredential: (
        name: string,
        value: string | null,
      ) => Promise<DesktopCredentialStatus>;
    };
  }
}
