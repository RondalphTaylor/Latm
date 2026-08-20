const supportedTradingModes = ["paper"] as const;

export type TradingMode = (typeof supportedTradingModes)[number];

export interface AppConfig {
  readonly tradingMode: TradingMode;
  readonly backendApiUrl: string;
}

function isTradingMode(value: string): value is TradingMode {
  return supportedTradingModes.some((mode: TradingMode): boolean => mode === value);
}

function parseTradingMode(value: string | undefined): TradingMode {
  if (value === undefined) {
    return "paper";
  }

  if (!isTradingMode(value)) {
    throw new Error(
      `Unsupported TRADING_MODE "${value}". Supported values: ${supportedTradingModes.join(", ")}.`,
    );
  }

  return value;
}

function parseBackendApiUrl(value: string | undefined): string {
  const rawValue = value ?? "http://localhost:8000";
  const parsed = new URL(rawValue);

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("BACKEND_API_URL must use http or https.");
  }

  return parsed.toString().replace(/\/$/, "");
}

export function getAppConfig(): Readonly<AppConfig> {
  return {
    tradingMode: parseTradingMode(process.env.TRADING_MODE),
    backendApiUrl: parseBackendApiUrl(process.env.BACKEND_API_URL),
  };
}
