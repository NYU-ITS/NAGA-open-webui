import { writable } from 'svelte/store';

export type TutorialStep = {
	stepIndex: number;
	selector: string | null; // CSS selector for the target DOM element, null = no highlight
	title: string;
	message: string;
	copyText?: string; // optional copy button content for step 5
	freeInteract?: boolean; // when true the overlay is non-blocking so users can edit inputs freely
	tooltipPlacement?: 'above' | 'below' | 'auto'; // force tooltip position relative to spotlight
	extraSpotlights?: string[]; // additional CSS selectors to spotlight visually alongside the primary
	selectAll?: boolean; // when true, querySelectorAll is used — all matches are spotlighted and any click advances
	advanceOn?: string; // custom window event name — tutorial advances on this event instead of a click
};

const LLM_FUNCTION_CODE = `"""
title: Pilot-GenAI AI Models
author: GenAI Developer Team
version: 1.0 [BetaQA]
description: Advanced AI model integration for Pilot-GenAI platform
"""

"""
================================================================
                    PILOT-GENAI AI MODELS
================================================================

Welcome to Pilot-GenAI platform!

This pipe provides seamless access to multiple AI providers
through our enhanced Pilot-GenAI platform, with secure
API Gateway from Portkey AI.

Paste your Portkey API Key in the Valves section to get started.

Ready to build amazing AI applications with Pilot-GenAI!
================================================================
"""

# CODE STARTS HERE
from pydantic import BaseModel, Field
import requests


class Pipe:
    class Valves(BaseModel):
        PORTKEY_API_KEY: str = Field(
            default="",
            description="Paste you Portkey API Key here",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.DEBUG = False
        self.PORTKEY_API_BASE_URL = "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
        self.PORTKEY_MODELS_API_URL = "https://api.portkey.ai/v2"

    def pipes(self):
        """
        Fetch and return available models from Portkey API
        """
        if self.DEBUG:
            print(f"[DEBUG] pipes() called - fetching models from Portkey API")
            print(f"[DEBUG] API URL: {self.PORTKEY_MODELS_API_URL}/models")

        try:
            headers = {
                'x-portkey-api-key': self.valves.PORTKEY_API_KEY,
                'Content-Type': 'application/json'
            }

            url = f'{self.PORTKEY_MODELS_API_URL}/models'
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            models_data = data.get('data', [])

            if self.DEBUG:
                print(f"[DEBUG] Successfully fetched {len(models_data)} models from Portkey API")
                print(f"[DEBUG] Response status: {response.status_code}")

            models = []
            for model in models_data:
                model_id = model.get('id', '')
                model_slug = model.get('slug', '')

                # Create clean name from slug
                friendly_name = model_slug.replace('-', ' ').title()

                # Fix common model name patterns
                friendly_name = friendly_name.replace('Gpt', 'GPT')
                friendly_name = friendly_name.replace('4O', '4o')

                models.append({
                    "id": model_id,
                    "name": friendly_name
                })

                if self.DEBUG:
                    print(f"[DEBUG] Model: {model_id} -> {friendly_name}")

            if self.DEBUG:
                print(f"[DEBUG] Returning {len(models)} models to user")

            return models

        except Exception as e:
            if self.DEBUG:
                print(f"[DEBUG] Error fetching models: {str(e)}")
                print(f"[DEBUG] Returning empty model list")
            return []

    def pipe(self, body: dict, __user__: dict):
        if self.DEBUG:
            print(f"[DEBUG] pipe() called")
            print(f"[DEBUG] User: {__user__.get('name', 'Unknown')} (ID: {__user__.get('id', 'Unknown')})")
            print(f"[DEBUG] Model: {body.get('model', 'Unknown')}")
            print(f"[DEBUG] Stream: {body.get('stream', False)}")
            print(f"[DEBUG] Messages count: {len(body.get('messages', []))}")

        try:
            headers = {
                "x-portkey-api-key": self.valves.PORTKEY_API_KEY,
                "Content-Type": "application/json",
            }

            # Clean model ID
            model_id = body.get('model', '')
            if '.' in model_id:
                # Extract the actual model ID after the pipe name prefix
                model_id = model_id.split('.', 1)[1]
                if self.DEBUG:
                    print(f"[DEBUG] Cleaned model ID: {model_id}")

            # Prepare payload - model name already includes @virtual-key/ format
            payload = {
                k: v
                for k, v in {
                    **body,
                    "model": model_id,
                    "temperature": body.get("temperature"),
                    "top_p": body.get("top_p"),
                    "frequency_penalty": body.get("frequency_penalty"),
                    "presence_penalty": body.get("presence_penalty"),
                    "max_tokens": body.get("max_tokens"),
                    "stop": body.get("stop"),
                    "seed": body.get("seed"),
                    "logit_bias": body.get("logit_bias"),
                }.items()
                if v is not None
            }

            if self.DEBUG:
                print(f"[DEBUG] Sending request to: {self.PORTKEY_API_BASE_URL}/chat/completions")
                print(f"[DEBUG] Payload keys: {list(payload.keys())}")
                if 'messages' in payload:
                    print(f"[DEBUG] First message: {payload['messages'][0] if payload['messages'] else 'No messages'}")

            response = requests.post(
                url=f"{self.PORTKEY_API_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
            )
            response.raise_for_status()

            if self.DEBUG:
                print(f"[DEBUG] Response status: {response.status_code}")
                print(f"[DEBUG] Response headers: {dict(response.headers)}")

            if body.get("stream", False):
                if self.DEBUG:
                    print(f"[DEBUG] Returning streaming response")
                return response.iter_lines()
            else:
                result = response.json()
                if self.DEBUG:
                    print(f"[DEBUG] Returning non-streaming response")
                    if 'choices' in result and result['choices']:
                        print(f"[DEBUG] Response length: {len(result['choices'][0].get('message', {}).get('content', ''))}")
                return result

        except Exception as e:
            if self.DEBUG:
                print(f"[DEBUG] Error in pipe(): {str(e)}")
                print(f"[DEBUG] Error type: {type(e).__name__}")
            return f"Error: {e}"
`;

export const SETUP_LLM_STEPS: TutorialStep[] = [
	{
		stepIndex: 0,
		selector: null,
		title: 'Welcome to the Admin Setup Guide',
		message:
			"This guide will walk you through setting up an LLM Function for your workspace. Follow each step and we'll get you up and running in just a few minutes."
	},
	{
		stepIndex: 1,
		selector: '#tutorial-user-menu-btn',
		title: 'Step 1 of 8 — Open your menu',
		message: 'Click the avatar to start.'
	},
	{
		stepIndex: 2,
		selector: '#tutorial-admin-panel-link',
		title: 'Step 2 of 8 — Admin Panel',
		message: 'Find Admin Panel in the avatar menu.'
	},
	{
		stepIndex: 3,
		selector: '#tutorial-admin-functions-tab',
		title: 'Step 3 of 8 — Functions',
		message: "Let's first set up an LLM Function."
	},
	{
		stepIndex: 4,
		selector: '#tutorial-functions-add-btn',
		title: 'Step 4 of 8 — Create a Function',
		message: 'Create a new Function by clicking the + button.'
	},
	{
		stepIndex: 5,
		selector: '#tutorial-function-editor-save',
		title: 'Step 5 of 8 — Configure the Function',
		message:
			'1. Put "LLM" in the Function Title and Function Description.\n2. Click "Copy Code" below and paste it, replacing all existing code.\n3. Hit Save.',
		copyText: LLM_FUNCTION_CODE,
		freeInteract: true, // user needs to type in inputs and code editor — tooltip pins to corner
		advanceOn: 'tutorial:function-saved', // advance only when the API save succeeds, not on click
		extraSpotlights: [
			'#tutorial-function-name',
			'#tutorial-function-description',
			'#tutorial-code-editor'
		]
	},
	{
		stepIndex: 6,
		selector: '#tutorial-functions-valves-btn',
		title: 'Step 6 of 8 — Open Valves',
		message: 'Click the gear icon next to your new LLM function.'
	},
	{
		stepIndex: 7,
		selector: '#tutorial-valves-save',
		title: 'Step 7 of 8 — Enter your API Key',
		message: 'Click "Default", paste your PortKey API Key, then hit Save.'
	},
	{
		stepIndex: 8,
		selector: '.tutorial-function-switch',
		title: 'Step 8 of 8 — Enable the Function',
		message: "Don't forget to enable the chosen function.",
		selectAll: true // highlight every switch on the page — clicking any one advances
	},
	{
		stepIndex: 9,
		selector: null,
		title: '🎉 LLM Setup Complete!',
		message:
			"You've completed the LLM Setup. Refresh the page and start a new chat — your model should be there!"
	}
];

export type TutorialState = {
	active: boolean;
	currentStep: number;
	tutorialId: string | null;
};

export const tutorialState = writable<TutorialState>({
	active: false,
	currentStep: 0,
	tutorialId: null
});

export function startTutorial(tutorialId: string) {
	tutorialState.set({ active: true, currentStep: 0, tutorialId });
}

export function nextTutorialStep() {
	tutorialState.update((s) => ({ ...s, currentStep: s.currentStep + 1 }));
}

export function prevTutorialStep() {
	tutorialState.update((s) => ({ ...s, currentStep: Math.max(0, s.currentStep - 1) }));
}

export function dismissTutorial() {
	tutorialState.set({ active: false, currentStep: 0, tutorialId: null });
}
