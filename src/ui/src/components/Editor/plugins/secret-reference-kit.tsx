import { toPlatePlugin } from "platejs/react";
import { BaseSecretReferencePlugin } from "./secret-reference-base";
import { SecretReferenceElement, SecretReferenceElementStatic } from "@/components/plate-ui/secret-reference-node";

export const SecretReferenceKit = [toPlatePlugin(BaseSecretReferencePlugin).withComponent(SecretReferenceElement)];
export const BaseSecretReferenceKit = [BaseSecretReferencePlugin.withComponent(SecretReferenceElementStatic)];
