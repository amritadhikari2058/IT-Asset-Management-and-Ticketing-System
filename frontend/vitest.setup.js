/**
 * Vitest setup file for jsdom environment.
 * This file is run before each test to set up browser globals.
 */
global.document = require('jsdom').jsdom('<!DOCTYPE html><html><head></head><body></body></html>');
global.window = document.defaultView;
global.navigator = global.window.navigator;
global.location = global.window.location;