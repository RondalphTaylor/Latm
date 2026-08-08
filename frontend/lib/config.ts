const supportedTradingModes = ["paper"] as const;

export type TradingMode = (typeof supportedTradingModes)[number];

export interface AppConfig {
  readonly tradingMode: TradingMode;
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

export function getAppConfig(): Readonly<AppConfig> {
  return {
    tradingMode: parseTradingMode(process.env.TRADING_MODE),
  };
}
