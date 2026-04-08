import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  spring,
  Sequence,
} from "remotion";
import "../style.css";

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({ frame, fps, config: { damping: 12 } });
  const opacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill className="items-center justify-center bg-gradient-to-br from-gray-900 via-blue-950 to-gray-900">
      <div style={{ transform: `scale(${scale})`, opacity }}>
        <h1 className="text-8xl font-bold text-white tracking-tight">
          Trading Bot
        </h1>
        <p className="text-3xl text-blue-400 mt-4 text-center font-light">
          Automated Crypto Trading
        </p>
      </div>
    </AbsoluteFill>
  );
};

const Features: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const features = [
    "Edge Indicator Strategy",
    "Multi-Exchange Support",
    "Real-Time Dashboard",
    "WhatsApp Notifications",
  ];

  return (
    <AbsoluteFill className="items-center justify-center bg-gradient-to-br from-gray-900 via-blue-950 to-gray-900">
      <div className="flex flex-col gap-8">
        {features.map((feature, i) => {
          const delay = i * 15;
          const s = spring({ frame: frame - delay, fps, config: { damping: 12 } });
          const opacity = interpolate(frame - delay, [0, 10], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          return (
            <div
              key={feature}
              style={{
                transform: `translateX(${interpolate(s, [0, 1], [100, 0])}px)`,
                opacity,
              }}
              className="flex items-center gap-4"
            >
              <div className="w-3 h-3 rounded-full bg-blue-500" />
              <span className="text-4xl text-white font-medium">{feature}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill className="items-center justify-center bg-gradient-to-br from-gray-900 via-blue-950 to-gray-900">
      <div style={{ opacity }} className="text-center">
        <h2 className="text-7xl font-bold text-white">Start Trading</h2>
        <p className="text-3xl text-blue-400 mt-6">24/7 Automated</p>
      </div>
    </AbsoluteFill>
  );
};

export const TradingBotIntro: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence durationInFrames={100}>
        <Title />
      </Sequence>
      <Sequence from={100} durationInFrames={120}>
        <Features />
      </Sequence>
      <Sequence from={220}>
        <Outro />
      </Sequence>
    </AbsoluteFill>
  );
};
