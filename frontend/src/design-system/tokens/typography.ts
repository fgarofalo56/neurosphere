import { tokens } from "@fluentui/react-components";

/** Typography scale expressed as Fluent token references (no literal sizes or colors). */
export interface TypeStyle {
  readonly fontSize: string;
  readonly lineHeight: string;
  readonly fontWeight: string;
  readonly fontFamily: string;
}

export type TypeScaleName = "caption" | "body" | "bodyStrong" | "subtitle" | "title" | "display";

export const typographyScale: Readonly<Record<TypeScaleName, TypeStyle>> = {
  caption: {
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    fontWeight: tokens.fontWeightRegular,
    fontFamily: tokens.fontFamilyBase,
  },
  body: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    fontWeight: tokens.fontWeightRegular,
    fontFamily: tokens.fontFamilyBase,
  },
  bodyStrong: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    fontWeight: tokens.fontWeightSemibold,
    fontFamily: tokens.fontFamilyBase,
  },
  subtitle: {
    fontSize: tokens.fontSizeBase500,
    lineHeight: tokens.lineHeightBase500,
    fontWeight: tokens.fontWeightSemibold,
    fontFamily: tokens.fontFamilyBase,
  },
  title: {
    fontSize: tokens.fontSizeHero700,
    lineHeight: tokens.lineHeightHero700,
    fontWeight: tokens.fontWeightSemibold,
    fontFamily: tokens.fontFamilyBase,
  },
  display: {
    fontSize: tokens.fontSizeHero900,
    lineHeight: tokens.lineHeightHero900,
    fontWeight: tokens.fontWeightBold,
    fontFamily: tokens.fontFamilyBase,
  },
};
